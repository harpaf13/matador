# coding: utf-8
""" This file implements the general wrapper to
structural similarity metrics.
"""
# matador modules
from matador.similarity.pdf_similarity import PDF
from matador.utils.cursor_utils import get_array_from_cursor
# external libraries
import numpy as np
# standard library
from collections import defaultdict


def get_uniq_cursor(cursor, sim_calculator=PDF, sim_tol=5e-2, energy_tol=5e-2,
                    enforce_same_stoich=True, projected=False,
                    debug=False, **sim_calc_args):
    """ Uses sim_calculator to filter cursor into unique structures to some
    tolerance sim_tol,additionally returning a dict of duplicates and the
    correlation matrix.

    Inputs:

        cursor              : matador cursor to be filtered
        sim_calculator      : fingerprint object type to compare
        sim_tol             : tolerance in similarity distance for duplicates
        energy_tol          : compare only structures within a certain energy tolerance (if enforce_same_stoich is False, this is disabled)
        enforce_same_stoich : compare only structures of the same stoichiometry
        projected           : use element-projected PDF to calculate similarity
        debug               : print timings and list similarities
        sim_calc_args       : dict containing parameters to pass to sim_calculator

    Returns:

        distinct_set        : a set of indices of unique documents
        dupe_dict           : a dict with keys from distinct_set, listing duplicates
        fingerprint_list    : a list <SimilarityCalculator> objects
        sim_mat             : the correlation matrix of pair similarity distances

    """
    fingerprint_list = []
    if enforce_same_stoich:
        energy_tol = 1e20
    if projected:
        sim_calc_args['projected'] = True
    print('Calculating fingerprints...')
    if debug:
        import time
    try:
        import progressbar
        bar = progressbar.ProgressBar(term_width=80)
    except(ImportError):
        def bar(cursor):
            return cursor
    for doc in bar(cursor):
        if debug:
            start = time.time()
        fingerprint_list.append(sim_calculator(doc, **sim_calc_args))
        if debug:
            completed = time.time() - start
            print('PDF of {} completed in {:0.1f} s'.format(' '.join(doc['text_id']), completed))

    sim_mat = np.ones((len(fingerprint_list), len(fingerprint_list)))
    print('Assessing similarities...')
    try:
        import progressbar
        bar = progressbar.ProgressBar(term_width=80)
    except(ImportError):
        pass
    for i in bar(range(len(fingerprint_list))):
        sim_mat[i, i] = 0
        for j in range(i+1, len(fingerprint_list)):
            # are we checking stoichiometries, if so, ensure they're the same
            if (enforce_same_stoich is False or
                (sorted(cursor[j]['stoichiometry']) == sorted(cursor[i]['stoichiometry'])
                 and np.abs(cursor[j]['enthalpy_per_atom']
                            - cursor[i]['enthalpy_per_atom']) < energy_tol)):
                sim = fingerprint_list[i].get_sim_distance(fingerprint_list[j], projected=projected)
                sim_mat[i, j] = sim
                sim_mat[j, i] = sim
            else:
                sim = 1e10
                sim_mat[i, j] = sim
                sim_mat[i, j] = sim
            if debug and sim < sim_tol:
                print('{} similar to {} with distance {}'.format(' '.join(cursor[i]['text_id']),
                                                                 ' '.join(cursor[j]['text_id']),
                                                                 sim))
    rows, cols = np.where(sim_mat <= sim_tol)
    distinct_set = set()
    dupe_set = set()
    dupe_dict = defaultdict(list)
    for i in range(len(sim_mat)):
        distinct_set.add(i)
    for coord in zip(rows, cols):
        if coord[0] == coord[1]:
            pass
        elif coord[0] not in dupe_set:
            # distinct_set.add(coord[0])
            if coord[1] in distinct_set:
                distinct_set.remove(coord[1])
            dupe_set.add(coord[1])
            dupe_dict[coord[0]].append(coord[1])
    print('Done!')
    return distinct_set, dupe_dict, fingerprint_list, sim_mat


def plot_similarity_energy_correlation_matrix(cursor, sim_mat, sim_vmin=0.05, sim_vmax=0.5):
    """ Plot a correlation heatmap where the upper triangular displays
    relative energy differences and the lower triangular displays
    structural similarity distance.

    TO-DO:
    * guidelines for different stoichiometries

    Inputs:

        cursor   : a matador cursor
        sim_mat  : matrix where S_{ij} = similarity distance(i, j)
        sim_vmin : sim distance at which to show minimum colour
        sim_vmax : "---------------------------" maximum "----"

    """
    import matplotlib.pyplot as plt
    import seaborn as sns
    assert(len(cursor) == len(sim_mat))
    energy_list = get_array_from_cursor(cursor, 'enthalpy_per_atom')
    energy_mat = np.zeros_like(sim_mat)
    for i in range(len(sim_mat)):
        for j in range(i+1, len(sim_mat)):
            energy_mat[i][j] = (energy_list[j] - energy_list[i])
    _sim_mat = np.tril(sim_mat)
    sim_mask = np.zeros_like(sim_mat, dtype=np.bool)
    sim_mask[np.triu_indices(len(sim_mask), k=1)] = True

    _energy_mat = np.triu(energy_mat)
    energy_mask = np.zeros_like(sim_mat, dtype=np.bool)
    energy_mask[np.tril_indices(len(sim_mask), k=1)] = True

    f, axarr = plt.subplots(ncols=2, nrows=2, figsize=(10, 10),
                            gridspec_kw={'height_ratios': [20, 1],
                                         'width_ratios': [20, 1]})
    cmap_energy = sns.cubehelix_palette(as_cmap=True, rot=-.4, light=1, start=1.5)
    cmap_sim = sns.cubehelix_palette(as_cmap=True, rot=.4, light=1, start=1.5)

    ax = axarr[0][0]
    axarr[1][1].axis('off')

    sns.heatmap(_sim_mat, mask=sim_mask, cmap=cmap_sim,
                vmin=sim_vmin, vmax=sim_vmax, ax=ax,
                xticklabels=False, yticklabels=False, square=True,
                cbar_kws={'label': 'structural similarity distance',
                          'orientation': 'horizontal'},
                cbar_ax=axarr[1][0])
    sns.heatmap(_energy_mat, mask=energy_mask, cmap=cmap_energy,
                vmax=0.05, vmin=0.0, ax=ax,
                xticklabels=False, yticklabels=False, square=True,
                cbar_kws={'label': 'enthalpy difference (eV/atom)'},
                cbar_ax=axarr[0][1])
    return