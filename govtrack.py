#!/usr/bin/env python

"""
Analyze congressional partisanship using the tools of Social Network Analysis.

This script will download data from govtrack.us on bills that were introduced
in a specific meeting of congress and for one of the two houses. The bill data
is then used to construct a network of congressional members where edges
between members of congress are based on the number of bills the two members
have cosponsored together.

Since the downloading of bill data can take a very long time and put stress on
the free (and excellent) govtrack.us API, this script automatically caches the
downloaded data after its first retrieval. The data is cached into a hidden
directory called .cache in the same directory where the script is located. To
ignore the cached data and retrieve it again, you can use the --ignore-cache
option.
"""

import os
import urllib2
import re
import copy
import argparse
try:
    import simplejson as json
except ImportError:
    import json

import networkx as nx
import matplotlib.pyplot as plt

import url
import progress


class GovTrackURL(url.URL):
    def __init__(self, netloc='www.govtrack.us', **kwargs):
        super(GovTrackURL, self).__init__(netloc=netloc, **kwargs)


def get_bills(congress, house, limit=None):
    """Returns an iterator over the bills introduced in the given congress.

    Arguments:
    congress -- the number for the meeting of congress (the ???th congress)
    house -- the house ([lower|representatives] or [upper|senate])

    Keyword Arguments:
    limit -- the number of bills to return
    """
    path = '/api/v2/bill'
    if house in ['lower', 'representatives']:
        bill_type = 'house_bill'
    elif house in ['upper', 'senate']:
        bill_type = 'senate_bill'
    else:
        raise ValueError('invalid value for house, expected lower (representatives) or upper (senate): %s' % house)
    return query_api(path, congress=congress, bill_type=bill_type, limit=limit)


def query_api(path, limit=None, **kwargs):
    """Returns an iterator over the objects returned from the govtrack.us API.

    All additional keyword paramaters are passed onto the govtrack.us API in
    the form of key/value pairs in the querystring of the URL. For further
    information on the parameters available see the govtrack.us API docs at
    http://www.govtrack.us/developers/api.

    Arguments:
    path -- the filepath of the API endpoint to query

    Keyword Arguments:
    limit -- the number of objects to return. If None (default), all objects
        are returned
    """
    url = GovTrackURL(path=path, **kwargs)
    while True:
        response = json.load(urllib2.urlopen(url.to_string()))
        meta = response['meta']
        objects = response['objects']
        offset = meta['offset']
        limit = limit if limit is not None else meta['total_count']
        for obj in objects:
            offset += 1
            progress = int((float(offset)/limit) * 100)
            obj_url = GovTrackURL(path='%s/%s' % (path, obj['id']))
            yield json.load(urllib2.urlopen(obj_url.to_string())), progress

            # If the limit argument is set, exit after we've reached that limit
            if limit is not None and offset >= limit:
                return

        # Update the current offset value and, if we've retrieved all of the
        # objects available, exit this function
        url.offset = meta['offset'] + meta['limit']
        # if url.offset > meta['total_count']:
        #     return


def party_affiliation(name):
    """Returns the member's political party affiliation

    Given a name with the following format:
        TITLE FIRST_NAME LAST_NAME [PARTY_AFFILIATION-DISTRICT_OR_STATE]
    this function parses out the party affiliation and returns it.
    """
    parties = {'R': 'republican', 'D': 'democrat', 'I': 'independent'}
    party_abbrev = re.search('\[([A-Z])-[A-Z]{2}[^\]]*\]', name).groups()[0]
    try:
        return parties[party_abbrev]
    except KeyError:
        return party_abbrev


def clean_node_attr_dict(attr_dict):
    """Cleans up the given node attribute dict.

    This function is used to clean up a node's attribute dict before adding
    it to the graph. It removes some attributes that are unnecessary and
    potentially harmful when writing the graph to disk and adds the node's
    party affiliation.

    Arguments:
    attr_dict -- the node attribute dict to be cleaned
    """
    n = copy.deepcopy(attr_dict)
    del n['youtubeid']
    del n['twitterid']
    del n['cspanid']
    n['party_affiliation'] = party_affiliation(n['name'])
    return n


def create_graph(bills):
    """Creates a Networkx graph for the given list of bills

    This function creates a graph where the nodes represent members of congress
    and the the edges between them represent that the two members have worked
    together on a bill. Each edge has a weight value based on the number of
    bills the two members have worked on together.

    Arguments:
    bills -- a list of dicts where each dict represents a bill in congress
    """
    g = nx.Graph()
    for bill in bills:
        sponsor = clean_node_attr_dict(bill['sponsor'])
        if not g.has_node(sponsor['bioguideid']):
            g.add_node(sponsor['bioguideid'], attr_dict=sponsor)
        for cosponsor in bill['cosponsors']:
            cosponsor = clean_node_attr_dict(cosponsor)
            if not g.has_node(cosponsor['bioguideid']):
                g.add_node(cosponsor['bioguideid'], attr_dict=cosponsor)
            if g.has_edge(sponsor['bioguideid'], cosponsor['bioguideid']):
                g[sponsor['bioguideid']][cosponsor['bioguideid']]['weight'] += 1
            else:
                g.add_edge(sponsor['bioguideid'], cosponsor['bioguideid'], attr_dict={'weight': 1})
    return g


def trim_edges(graph, weight=1):
    """Returns a copy of the given graph with edges trimmed by weight.

    Arguments_api:
    graph -- the graph to trim
_api
    Keyword arguments:
    weight -- the value for which all edges with weights equal to, or less than
        it, will be removed (default 1).
    """
    g = graph.copy()
    trimmed_edges = []
    for u, v in g.edges():
        if g[u][v]['weight'] <= weight:
            trimmed_edges.append((u, v))
    g.remove_edges_from(trimmed_edges)
    return g


def sort_nodes(graph, m, desc=True):
    """Returns a list of nodes sorted according to the given mapping.

    Arguments:
    graph -- the graph whose nodes will be sorted
    m -- a mapping (dict) of nodes to their relative value in the graph

    Keyword Arguments:
    desc -- set to True to sort descending (default), False for ascending
    """
    sorted_keys = sorted(m.iteritems(), key=lambda (k, v): (v, k), reverse=desc)
    nodes = [graph.node[k] for k, _ in sorted_keys]
    return nodes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('congress', type=int, metavar='CONGRESS',
        help='the number for the meeting of congress (the ???th congress)')
    parser.add_argument('house', type=str, metavar='HOUSE',
        choices=['lower', 'representatives', 'upper', 'senate'],
        help='the house ([lower|representatives] or [upper|senate])')
    parser.add_argument('--ignore-cache', action='store_true',
        help='ignore the cache and do a fresh download all bills from govtrack.us')
    parser.add_argument('--limit', '-l', type=int, action='store', default=None,
        help='the number of bills to download (downloads all bills by default)')
    parser.add_argument('--trim', '-t', type=int, action='store', default=None,
        help='remove all edges with a weight at or below the trim value')
    parser.add_argument('--betweenness', '-b', action='store_true',
        help='resize the nodes in the graph according to their betweenness')
    args = parser.parse_args()

    # Create the .cache directory if it doesn't already exist
    root_dir = os.path.dirname(os.path.realpath(__file__))
    cache_dir = os.path.join(root_dir, '.cache')
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    # Get the bills (either from cache or a fresh download)
    house = 'lower' if args.house in ['lower', 'representatives'] else 'senate'
    cache_filepath = os.path.join(cache_dir, '%s_%s.json' % (args.congress, house))
    if args.ignore_cache or not os.path.exists(cache_filepath):
        bills = []
        progress.progress_bar(0)
        for bill, i in get_bills(args.congress, args.house, limit=args.limit):
            bills.append(bill)
            progress.progress_bar(i)
        with open(cache_filepath, 'w') as fout:
            json.dump(bills, fout)
    else:
        with open(cache_filepath, 'r') as fin:
            bills = json.load(fin)

    g = create_graph(bills)
    if args.trim is not None:
        g = trim_edges(g, weight=args.trim)
    pos = nx.fruchterman_reingold_layout(g)
    dems = [n for n in g.nodes() if g.node[n]['party_affiliation'] == 'democrat']
    reps = [n for n in g.nodes() if g.node[n]['party_affiliation'] == 'republican']
    inds = [n for n in g.nodes() if g.node[n]['party_affiliation'] == 'independent']

    # Removing the weakest edges before calculating the betweenness centralities.
    # This is mainly just for visualization purposes, so you can visually discern
    # who has the greatest betweenness.
    b = nx.centrality.betweenness_centrality(trim_edges(g, weight=10), normalized=False)
    node_size = lambda n: b[n] if args.betweenness else 300

    nx.draw_networkx_nodes(g, pos, nodelist=dems, node_color='blue', node_size=map(node_size, dems))
    nx.draw_networkx_nodes(g, pos, nodelist=reps, node_color='red', node_size=map(node_size, reps))
    nx.draw_networkx_nodes(g, pos, nodelist=inds, node_color='gray', node_size=map(node_size, inds))
    nx.draw_networkx_edges(g, pos, alpha=0.05)
    plt.show()

