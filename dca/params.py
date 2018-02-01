import argparse
import inspect
import logging
import random
import sys

import numpy as np

import fixedstrats  # noqa
import strats  # noqa


def strat_classes(module_name):
    """
    Return a list with (name, class) for all the strats
    """

    def is_class_member(member):
        return inspect.isclass(member) and member.__module__ == module_name

    clsmembers = inspect.getmembers(sys.modules[module_name], is_class_member)
    return clsmembers


def get_pparams(defaults=False):
    """
    Return problem parameters and chosen strategy class. If 'defaults' is True,
    just return the default params.
    """
    parser = argparse.ArgumentParser(
        description='DCA',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    stratclasses = strat_classes("strats") + strat_classes("fixedstrats")
    stratnames = ['show']
    for i in range(len(stratclasses)):
        s = stratclasses[i]
        s1 = s[0].lower()
        s2 = s1.replace("strat", "")
        if s2 not in ["net", "qnet", "rl", "qtable"]:
            stratnames.append(s2)
        stratclasses[i] = (s2, stratclasses[i][1])
    weight_initializers = ['zeros', 'glorot_unif', 'glorot_norm', 'norm_cols']

    parser.add_argument(
        '--strat', type=str, choices=stratnames, default="rs_sarsa")
    parser.add_argument(
        '--rows', type=int, help="number of rows in grid", default=7)
    parser.add_argument(
        '--cols', type=int, help="number of columns in grid", default=7)
    parser.add_argument(
        '--n_channels', type=int, help="number of channels", default=70)
    parser.add_argument(
        '--erlangs',
        type=float,
        help="erlangs = call_rate * call_duration"
        "\n 10 erlangs = 200 call rate, given call duration of 3"
        "\n 7.5 erlangs = 150cr, 3cd"
        "\n 5 erlangs = 100cr, 3cd",
        default=10)
    parser.add_argument(
        '--call_rates', type=int, help="in calls per minute", default=None)
    parser.add_argument(
        '--call_duration', type=int, help="in minutes", default=3)
    parser.add_argument(
        '--p_handoff', type=float, help="handoff probability", default=0.15)
    parser.add_argument(
        '--hoff_call_duration',
        type=int,
        help="handoff call duration, in minutes",
        default=1)
    parser.add_argument(
        '--n_events',
        '-i',
        dest='n_events',
        type=int,
        help="number of events to simulate",
        default=470000)
    parser.add_argument(
        '--n_hours',
        type=float,
        help="Number of hours to simulate (overrides n_events)",
        default=None)
    parser.add_argument(
        '--avg_runs',
        metavar='N',
        type=int,
        help="Run simulation N times, report average scores",
        default=None)

    parser.add_argument(
        '--alpha', type=float, help="(RL/Table) learning rate", default=0.036)
    parser.add_argument(
        '--alpha_decay',
        type=float,
        help="(RL/Table) factor by which alpha is multiplied each iteration",
        default=0.999998)
    parser.add_argument(
        '--epsilon',
        '-eps',
        dest='epsilon',
        type=float,
        help="(RL) (initial) probability of choosing random action",
        default=0.75443)
    parser.add_argument(
        '--epsilon_decay',
        type=float,
        help="(RL) factor by which epsilon is multiplied each iteration",
        default=0.99999)
    parser.add_argument(
        '--gamma', type=float, help="(RL) discount factor", default=0.85)
    parser.add_argument(
        '--lambda',
        type=float,
        help="(RL/Table) lower lambda weighs fewer step returns higher",
        default=None)
    parser.add_argument(
        '--min_alpha',
        type=float,
        help="(RL) stop decaying alpha beyond this point",
        default=0.0)
    parser.add_argument(
        '--save_exp_data',
        help="Save experience data to file",
        action='store_true',
        default=False)
    parser.add_argument(
        '--restore_qtable',
        nargs='?',
        type=str,
        help="(RL/Table) Restore q-values from file",
        default="",
        const="qtable.npy")
    parser.add_argument(
        '--hopt',
        nargs='?',
        choices=[
            'epsilon', 'epsilon_decay', 'alpha', 'alpha_decay', 'gamma',
            'lambda', 'net_lr', 'net_copy_iter', 'net_creep_tau', 'vf_coeff',
            'entropy_coeff'
        ],
        help="(Hopt) Hyper-parameter optimization with hyperopt."
        " Saves progress to 'results-{stratname}-{vars}.pkl' and"
        " automatically resumes if file already exists. Logs to file with "
        " same name besides extension .log.",
        default=None)
    parser.add_argument(
        '--hopt_best',
        type=str,
        help="(Hopt) Show best params found and corresponding loss for a"
        "given hopt file",
        default=None)
    parser.add_argument(
        '--hopt_plot',
        action='store_true',
        help="(Hopt) Plot params found and "
        "corresponding loss for a given strat",
        default=False)

    parser.add_argument(
        '--net_lr',
        '-lr',
        dest='net_lr',
        type=float,
        help="(Net) Learning rate. Overrides 'alpha'.",
        default=3.4e-5)
    parser.add_argument(
        '--weight_init_conv', choices=weight_initializers, default='zeros')
    parser.add_argument(
        '--weight_init_dense',
        choices=weight_initializers,
        default='norm_cols')
    parser.add_argument(
        '--dueling_qnet',
        '-duel',
        dest='dueling_qnet',
        action='store_true',
        help="(Net/Duel) Dueling QNet",
        default=False)
    parser.add_argument(
        '--no_double_qnet',
        action='store_true',
        help="(Net/Double) Disable Double QNet",
        default=False)
    parser.add_argument(
        '--layer_norm',
        action='store_true',
        help="(Net) Use layer normalization",
        default=False)
    parser.add_argument(
        '--no_empty_neg',
        action='store_true',
        help="(Net) Represent empty channels in grid as 0 instead of -1",
        default=False)
    parser.add_argument(
        '--act_fn',
        help="(Net) Activation function",
        choices=['relu', 'elu', 'leaky_relu'],
        default='relu')
    parser.add_argument(
        '--optimizer',
        '-opt',
        dest='optimizer',
        choices=['sgd', 'sgd-m', 'adam', 'rmsprop'],
        default='sgd-m')
    parser.add_argument(
        '--max_grad_norm',
        '-norm',
        dest='max_grad_norm',
        type=float,
        metavar='N',
        nargs='?',
        help="(Net) Clip gradient to N",
        default=None,
        const=100000)
    parser.add_argument(
        '--save_net',
        action='store_true',
        help="(Net) Save network params",
        default=False)
    parser.add_argument(
        '--restore_net',
        action='store_true',
        help="(Net) Restore network params",
        default=False)
    parser.add_argument(
        '--batch_size',
        type=int,
        help="(Net/Exp) Batch size for experience replay or training."
        "A value of 1 disables exp. replay",
        default=1)
    parser.add_argument(
        '--buffer_size',
        type=int,
        help="(Net/Exp) Buffer size for experience replay",
        default=5000)
    parser.add_argument(
        '--bench_batch_size',
        action='store_true',
        help="(Net) Benchmark batch size for neural network",
        default=False)
    parser.add_argument(
        '--net_copy_iter',
        type=int,
        metavar='N',
        help="(Net/Double) Copy weights from online to target "
        "net every N iterations",
        default=45)
    parser.add_argument(
        '--net_copy_iter_decr',
        type=int,
        metavar='N',
        help="(Net/Double) Decrease 'net_copy_iter' every N iterations",
        default=None)
    parser.add_argument(
        '--net_creep_tau',
        '-tau',
        dest='net_creep_tau',
        type=float,
        nargs='?',
        metavar='tau',
        help="(Net/Double) Creep target net 'tau' (0, 1] percent "
        "towards online net every 'net_copy_iter' iterations. "
        "Net copy iter should be decreased as tau decreases. "
        "'tau' ~ 0.1 when 'net_copy_iter' is 5 is good starting point.",
        default=1,
        const=0.12)
    parser.add_argument(
        '--vf_coeff',
        type=float,
        help="(Net/Pol) Value function coefficient in policy gradient loss",
        default=0.02)
    parser.add_argument(
        '--entropy_coeff',
        type=float,
        help="(Net/Pol) Entropy coefficient in policy gradient loss",
        default=10.0)
    parser.add_argument(
        '--train_net',
        type=int,
        metavar='N',
        nargs="?",
        help="(Net) Train network for 'N' passes",
        default=0,
        const=1)
    parser.add_argument(
        '--no_gpu',
        action='store_true',
        help="(Net) Disable TensorFlow GPU usage",
        default=False)

    parser.add_argument(
        '--rng_seed',
        type=int,
        metavar='N',
        nargs='?',
        help="By default, use seed 0. "
        "If specified without a value, use a random seed.",
        default=0,
        const=np.random.randint(2000))
    parser.add_argument(
        '--verify_grid',
        action='store_true',
        help="Verify channel reuse constraint each iteration",
        default=False)
    parser.add_argument(
        '--prof',
        dest='profiling',
        action='store_true',
        help="performance profiling",
        default=False)
    parser.add_argument(
        '--tfprof',
        dest='tfprofiling',
        metavar='DEST',
        type=str,
        help="(Net) performance profiling for TensorFlow."
        " Specify ouput file name",
        default="")
    parser.add_argument('--gui', action='store_true', default=False)
    parser.add_argument(
        '--plot', action='store_true', dest='do_plot', default=False)
    parser.add_argument(
        '--log_level',
        type=int,
        choices=[10, 20, 30],
        help="10: Debug,\n20: Info,\n30: Warning",
        default=logging.INFO)
    parser.add_argument(
        '--log_file',
        metavar='DEST',
        type=str,
        help="enable logging to given file name")
    parser.add_argument(
        '--log_iter',
        metavar='N',
        type=int,
        help="Show blocking probability and stats such as "
        "epsilon, learning rate and loss every N iterations",
        default=None)

    if defaults:
        args = parser.parse_args([])
    else:
        args = parser.parse_args()
    params = vars(args)

    params['empty_neg'] = not params['no_empty_neg']
    del params['no_empty_neg']
    params['double_qnet'] = not params['no_double_qnet']
    del params['no_double_qnet']
    params['dims'] = [params['rows'], params['cols'], params['n_channels']]

    # Sensible presets / overrides
    params['net'] = False  # Whether net is in use or not
    if "net" in params['strat'].lower():
        if not params['log_iter']:
            params['log_iter'] = 5000
        params['net'] = True
    else:
        if not params['log_iter']:
            params['log_iter'] = 50000
        params['batch_size'] = 1
    if not params['call_rates']:
        params['call_rates'] = params['erlangs'] / params['call_duration']
    if params['avg_runs']:
        params['gui'] = False
        params['log_level'] = logging.ERROR
    if params['hopt'] is not None:
        params['gui'] = False
        params['log_level'] = logging.ERROR
        # Since hopt only compares new call block rate,
        # handoffs are a waste of computational resources.
        params['p_handoff'] = 0
        # Always log to file so that parameters are recorded
        pnames = str.join("-", params['hopt'].keys())
        f_name = f"results-{params['strat']}-{pnames}"
        params['log_file'] = f_name
    if params['bench_batch_size']:
        params['log_level'] = logging.WARN

    random.seed(params['rng_seed'])
    np.random.seed(params['rng_seed'])

    for name, cls in stratclasses:
        if params['strat'].lower() == name.lower():
            stratclass = cls
    return params, stratclass


def non_uniform_preset(pp):
    raise NotImplementedError  # Untested
    """
    Non-uniform traffic patterns for linear array of cells.
    Formål: How are the different strategies sensitive to
    non-uniform call patterns?
    rows = 1
    cols = 20
    call rates: l:low, m:medium, h:high
    For each pattern, the numeric values of l, h and m are chosen
    so that the average call rate for a cell is 120 calls/hr.
    low is 1/3 of high; med is 2/3 of high.
    """
    avg_cr = 120 / 60  # 120 calls/hr
    patterns = [
        "mmmm" * 5, "lhlh" * 5, ("llh" * 7)[:20], ("hhl" * 7)[:20],
        ("lhl" * 7)[:20], ("hlh" * 7)[:20]
    ]
    pattern_call_rates = []
    for pattern in patterns:
        n_l = pattern.count('l')
        n_m = pattern.count('m')
        n_h = pattern.count('h')
        cr_h = avg_cr * 20 / (n_h + 2 / 3 * n_m + 1 / 3 * n_l)
        cr_m = 2 / 3 * cr_h
        cr_l = 1 / 3 * cr_h
        call_rates = np.zeros((1, 20))
        for i, c in enumerate(pattern):
            if c == 'l':
                call_rates[0][i] = cr_l
            elif c == 'm':
                call_rates[0][i] = cr_m
            elif c == 'h':
                call_rates[0][i] = cr_h
        pattern_call_rates.append(call_rates)
