import argparse
import os
import pickle

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from matplotlib.ticker import PercentFormatter

from datahandler import next_filename

params = {
    'legend.fontsize': 'x-large',
    'figure.figsize': (13, 11),
    'axes.labelsize': 'x-large',
    'axes.titlesize': 'x-large',
    'xtick.labelsize': 'x-large',
    'ytick.labelsize': 'x-large'
}
plt.rcParams.update(params)
ctypes = ['New call', 'Hand-off', 'Total']
ctypes_short = ['new', 'hoff', 'tot']
ctypes_map = dict(zip(ctypes_short, ctypes))


def plot_bps(all_block_probs_cums,
             log_iter,
             n_events,
             labels=None,
             ylabel=None,
             title='',
             fname=None):
    """ If labels=None and ylabel=None:
    Plot for each call type, for each log_iter, cumulative block prob

    all_block_probs_cums: For each call type (new, hoff, tot), for each run,
    cumulative block prob for each log iter [[run1_log1, run1_log2, ..],
    [run2_log1, run2_log2], ..]

    If fname is given, don't show plot but save it
    """
    if ylabel is None:
        ylabel = "Cumulative call blocking probability"
    if labels is None:
        labels = ctypes
        loc = 'upper right'
    else:
        loc = 'lower right'

    fig, ax = plt.subplots(1, 1)
    plt.plot()
    x = np.arange(log_iter, n_events + 1, log_iter)
    for i, block_probs_cums in enumerate(all_block_probs_cums):
        # Convert to percent
        y = 100 * np.mean(block_probs_cums, axis=0)
        std_devs = 100 * np.std(block_probs_cums, axis=0)
        ax.errorbar(x, y, yerr=std_devs, fmt='-o', label=labels[i], capsize=5)
    ax.legend(loc=loc)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Call events")
    ax.set_title(title)
    ax.yaxis.grid(True)
    ax.yaxis.set_major_formatter(PercentFormatter())
    ax.yaxis.set_major_locator(ticker.MultipleLocator(0.5))
    if n_events >= 400000:
        ax.xaxis.set_major_locator(ticker.MultipleLocator(50000))
    if not fname:
        plt.show()
    else:
        fname = next_filename(fname, '.png')
        if not os.path.exists("plots"):
            os.makedirs("plots")
        plt.savefig("plots/" + fname, bbox_inches='tight')


def plot_strats(data, labels=None, ctype='new', title='', fname=None):
    """Plot for each strat, for a specific call type ctype, cumulative
    block prob for each log iter.

    data: For each strat, a dict with:
    - datetime,
    - log_iter,
    - n_events,
    - for one or more call types, for each log iter, cumulative block prob
    """
    log_iter, n_events = data[0]['log_iter'], data[0]['n_events']
    for strat in data:
        assert log_iter == strat['log_iter'], (log_iter, strat['log_iter'])
        assert n_events == strat['n_events'], (n_events, strat['n_events'])
        print(strat['datetime'])
    all_block_probs_cums = (d[ctype] for d in data)
    if labels is None:
        labels = [None] * len(data)
    ylabel = f"{ctypes_map[ctype]} cumulative blocking probability"
    plot_bps(all_block_probs_cums, log_iter, n_events, labels, ylabel, title, fname)


def runner():
    parser = argparse.ArgumentParser(
        description='DCA', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        'fnames',
        type=str,
        nargs='+',
        help="File name(s) of cum block prob pickle file(s)",
        default=None)
    parser.add_argument(
        '--labels',
        type=str,
        nargs='*',
        help="Optional labels for corresponding pickle files",
        default=None)
    parser.add_argument(
        '--ctype',
        nargs='*',
        type=str,
        choices=ctypes_short,
        help="Call type to plot",
        default=None)
    parser.add_argument('--title', type=str, help="Call type to plot", default='')
    parser.add_argument(
        '--plot_save',
        type=str,
        help="Save plot to given file name, don't show",
        default=None)

    args = vars(parser.parse_args())
    data = []
    for fname in args['fnames']:
        with open('bps/' + fname + '.pkl', "rb") as f:
            data.append(pickle.load(f))
    labels = args['labels']
    if labels is not None:
        assert len(data) == len(labels), (len(data), len(labels))
    title = args['title']
    if len(data) == 1:
        all_block_probs_cums = (data[0][ctype] for ctype in ctypes_short)
        plot_bps(
            all_block_probs_cums,
            data[0]['log_iter'],
            data[0]['n_events'],
            title=title,
            fname=args['plot_save'])
    else:
        if len(args['ctype']) > 1:
            for ctype in args['ctype']:
                fname = args['plot_save'] + '-ctype'
                plot_strats(data, labels, ctype, title=title, fname=fname)
        plot_strats(data, labels, args['ctype'], title=title, fname=fname)


if __name__ == '__main__':
    runner()