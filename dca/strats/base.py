import signal
from typing import Tuple

import numpy as np

import gridfuncs_numba as NGF
from environment import Env
from eventgen import CEvent
from replaybuffer import PrioritizedReplayBuffer
from strats.exp_policies import exp_pol_funcs
from utils import LinearSchedule


class Strat:
    def __init__(self, pp, logger, pid="", gui=None, *args, **kwargs):
        self.rows, self.cols, self.n_channels = self.dims = pp['dims']
        self.pid = pid
        self.save = pp['save_exp_data']
        self.batch_size = pp['batch_size']
        self.n_hours, self.n_events = pp['n_hours'], pp['n_events']
        self.pp = pp
        self.logger = logger

        self.grid = np.zeros(pp['dims'], np.bool)
        # Contains hand-offs only
        self.hgrid = np.zeros(pp['dims'], np.bool)
        self.env = Env(pp, self.grid, self.hgrid, logger, pid)
        if (self.save or self.batch_size > 1):
            size = self.n_events if self.save else pp['buffer_size']
            self.exp_buffer = PrioritizedReplayBuffer(
                size=size,
                rows=self.rows,
                cols=self.cols,
                n_channels=self.n_channels,
                alpha=0.6)  # original: 0.6
            self.pri_beta_schedule = LinearSchedule(
                self.n_events,
                initial_p=0.4,  # pp['prioritized_replay_beta'],
                final_p=1.0)  # original: 1.0
            self.prioritized_replay_eps = float(1e-6)

        self.quit_sim, self.invalid_loss, self.exceeded_bthresh = False, False, False
        self.i, self.t = 0, 0.1  # Iteration, time
        signal.signal(signal.SIGINT, self.exit_handler)

    def exit_handler(self, *args):
        """
        Graceful exit on ctrl-c signal from
        command line or on 'q' key-event from gui.
        """
        self.logger.error("\nPremature exit")
        self.quit_sim = True

    def simulate(self) -> Tuple[float, float]:
        """
        Run simulation and return a tuple with cumulative call
        block probability and cumulative handoff block probability
        """
        cevent = self.env.init_calls()
        ch = self.get_init_action(cevent)

        # Discrete event simulation
        while self.continue_sim(self.i, self.t):
            self.t, ce_type, cell = cevent[0:3]
            grid = np.copy(self.grid)  # Copy before state is modified
            reward, discount, next_cevent = self.env.step(ch)
            next_ch = self.get_action(next_cevent, grid, cell, ch, reward, ce_type,
                                      discount)
            # NOTE Could do per-strat saving here, as they save different stuff
            if self.save \
                    and ch is not None \
                    and ce_type != CEvent.END:
                # Only add (s, a, r, s', a') tuples for which the events in
                # s is not an END events, and for which there is an
                # available action a.
                # If there is no available action, that is, there are no
                # free channels which to assign, the neural net is not used
                # for selection and so it should not be trained on that data.
                # END events are not trained on either because the network is
                # supposed to predict the q-values for different channel
                # assignments; however the channels available for reassignment
                # are always busy in a grid corresponding to an END event.
                next_grid = np.copy(self.grid)
                next_cell = next_cevent[2]
                self.exp_buffer.add(
                    grid, cell, ch, reward, next_grid=next_grid, next_cell=next_cell)

            if self.i > 0:
                if self.i % self.pp['log_iter'] == 0:
                    self.fn_report()
                # NOTE Could do per iteration stuff in strats
                if self.pp['net'] and \
                        self.i % self.net_copy_iter == 0:
                    self.update_target_net()
                if self.pp['net_copy_iter_decr'] and \
                   self.i % self.pp['net_copy_iter_decr'] == 0 and \
                   self.net_copy_iter > 1:
                    self.net_copy_iter -= 1
                    self.logger.info(f"Decreased net copy iter to {self.net_copy_iter}")
            if (self.env.stats.block_probs_cum and  # yapf: disable
                    self.env.stats.block_probs_cum[-1] > self.pp['breakout_thresh']):
                pid_str = "" if self.pid == "" else f"T{self.pid} "
                self.logger.error(
                    f"{pid_str}Block prob threshold exceeded "
                    f"at {self.env.stats.block_probs_cum[-1]:.4f}; breaking out early")
                self.quit_sim = True
                self.exceeded_bthresh = True
            ch, cevent = next_ch, next_cevent
            self.i += 1
        self.env.stats.end_episode(np.count_nonzero(self.grid))
        self.fn_after()
        if self.save:
            self.exp_buffer.save_experience_to_disk()
        if self.quit_sim and (self.pp['hopt'] or self.pp['dlib_hopt'] or self.pp['avg_runs']) \
           and not self.exceeded_bthresh:
            # Don't want to return actual block prob for incomplete sims when
            # optimizing params, because block prob is much lower at sim start
            if self.invalid_loss:
                (None, None, None)
            return (1, 1, 1)
        return (self.env.stats.block_prob_cum, self.env.stats.block_prob_cum_hoff,
                self.env.stats.block_prob_cum_tot)

    def continue_sim(self, i, t) -> bool:
        if self.quit_sim:
            return False  # Gracefully exit to print stats, clean up etc.
        elif self.n_hours is not None:
            return (t / 60) < self.n_hours
        else:
            return i < self.n_events

    def get_init_action(self, next_cevent) -> int:
        """Return a channel to be (re)assigned in response to 'next_cevent'."""
        raise NotImplementedError

    def get_action(self, next_cevent, grid, cell, ch, reward, ce_type, discount) -> int:
        """Return a channel to be (re)assigned in response to 'next_cevent'.

        'cell' and 'ch' specify the action that was previously executed on
        'grid' in response to an event of type 'ce_type', resulting in
        'reward'.
        """
        raise NotImplementedError

    def fn_report(self):
        """
        Report stats for different strategies
        """
        pass

    def fn_after(self):
        """
        Cleanup after simulation
        """
        pass


class RLStrat(Strat):
    def __init__(self, pp, *args, **kwargs):
        super().__init__(pp, *args, **kwargs)
        self.epsilon = self.epsilon0 = pp['epsilon']
        epol = exp_pol_funcs[pp['exp_policy']](c=pp['exp_policy_param'])
        self.exploration_policy = epol.select_action
        self.eps_log_decay = self.pp['eps_log_decay']

        self.epsilon_decay = pp['epsilon_decay']
        self.logger.info(f"NP seed: {np.random.get_state()[1][0]}")
        self.losses = [0]
        self.qval_means = []

    def fn_report(self):
        self.env.stats.report_rl(self.epsilon, self.alpha, self.losses, self.qval_means)

    def get_init_action(self, cevent):
        ch, *_ = self.optimal_ch(ce_type=cevent[1], cell=cevent[2])
        return ch

    def get_action(self, next_cevent, grid, cell, ch, reward, ce_type, discount) -> int:
        next_ce_type, next_cell = next_cevent[1:3]
        # Choose A' from S'
        next_ch, next_max_ch, p = self.optimal_ch(next_ce_type, next_cell)
        # If there's no action to take, or no action was taken,
        # don't update q-value at all
        if ce_type != CEvent.END and  \
           ch is not None and next_ch is not None:
            assert next_max_ch is not None
            # Observe reward from previous action, and
            # update q-values with one-step look-ahead
            self.update_qval(grid, cell, ch, reward, next_cell, next_ch, next_max_ch,
                             discount, p)
        return next_ch

    def optimal_ch(self, ce_type, cell) -> Tuple[int, float, int]:
        """Select the channel fitting for assignment that
        that has the maximum q-value according to an exploration policy,
        or select the channel for termination that has the minimum
        q-value in a greedy fashion.

        Return (ch, max_ch) where 'ch' is the selected channel according to
        exploration policy and max_ch' is the greedy (still eligible) channel.
        'ch' (and 'max_ch') is None if no channel is eligible for assignment.
        """
        inuse = np.nonzero(self.grid[cell])[0]
        n_used = len(inuse)

        if ce_type == CEvent.NEW or ce_type == CEvent.HOFF:
            chs = NGF.get_eligible_chs(self.grid, cell)
            if len(chs) == 0:
                # No channels available for assignment,
                return (None, None, 0)
        else:
            # Channels in use at cell, including channel scheduled
            # for termination. The latter is included because it might
            # be the least valueable channel, in which case no
            # reassignment is done on call termination.
            chs = inuse
            # or no channels in use to reassign
            assert n_used > 0

        # TODO If 'max_ch' turns out not to be useful, then don't return it and
        # avoid running a forward pass through the net if a random action is selected.
        qvals_dense = self.get_qvals(cell=cell, n_used=n_used, ce_type=ce_type, chs=chs)
        # Selecting a ch for reassigment is always greedy because no learning
        # is done on the reassignment actions.
        if ce_type == CEvent.END:
            amin_idx = np.argmin(qvals_dense)
            ch = max_ch = chs[amin_idx]
            p = 1
        else:
            ch, idx, p = self.exploration_policy(self.epsilon, chs, qvals_dense, cell)
            if self.eps_log_decay:
                self.epsilon = self.epsilon0 / np.sqrt(self.t * 60 / self.eps_log_decay)
            else:
                self.epsilon *= self.epsilon_decay
            amax_idx = np.argmax(qvals_dense)
            max_ch = chs[amax_idx]

        # If qvals blow up ('NaN's and 'inf's), ch becomes none.
        if ch is None:
            self.logger.error(f"ch is none for {ce_type}\n{chs}\n{qvals_dense}\n")
            raise Exception
        self.logger.debug(f"Optimal ch: {ch} for event {ce_type} of possibilities {chs}")
        return (ch, max_ch, p)


class NetStrat(RLStrat):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.net_copy_iter = self.pp['net_copy_iter']
        self.last_lr = 1

        self.avg_reward = 0
        frepfuncs = NGF.get_frep_funcs(self.pp['frep_type'])
        self.frepshape = frepfuncs['shape']
        self.afterstate_freps = frepfuncs['afterstate_freps']
        self.feature_rep = frepfuncs['feature_rep']
        self.feature_reps = frepfuncs['feature_reps']
        self.frep, self.next_frep = self.feature_rep(self.grid), None

    def fn_report(self):
        avg_reward = self.avg_reward if self.avg_reward != 0 else None
        self.env.stats.report_rl(self.epsilon, self.last_lr, self.losses, self.qval_means,
                                 avg_reward)
        if self.pp['print_weights']:
            self.env.stats.report_weights(*self.net.get_weights())

    def fn_after(self):
        # self.logger.info(
        #     f"TF Rand: {self.net.rand_uniform()}, NP seed: {np.random.get_state()[1][0]}")
        if self.pp['save_net']:
            inp = ""
            if self.quit_sim:
                while inp not in ["Y", "N"]:
                    inp = input("Premature exit. Save model? Y/N: ").upper()
            if inp in ["", "Y"]:
                self.net.save_model()
        self.net.save_timeline()
        self.net.sess.close()

    def backward(self, *args, **kwargs):
        loss, self.last_lr, td_errs = self.net.backward(*args, **kwargs)
        if np.isinf(loss) or np.isnan(loss):
            self.logger.error(f"Invalid loss: {loss}")
            self.invalid_loss, self.quit_sim = True, True
        else:
            self.losses.append(loss)
        return td_errs
