#!/usr/bin/env python
"""
Off-the-shelf PIBOSO tagger

Marco Lui, March 2013
"""

import argparse, sys, os
import csv
import tempfile

from hydrat.store import Store

# Disable hydrat's progressbar output
import hydrat.common.pb as pb
pb.ENABLED = False

from piboso.tokenize import induce
from piboso.common import Timer
from piboso.model import load_model, load_default_model
from piboso.config import load_config, write_blank_config, DEFAULT_CONFIG_FILE

import numpy as np
import scipy.sparse as sp

def main():
  # TODO: check temp is cleared
  # TODO: configurable tempdir
  # TODO: accept paths on STDIN
  parser = argparse.ArgumentParser()
  parser.add_argument("abstracts", metavar="FILE", help="do PIBOSO tagging for FILE (can specify multiple)", nargs='*')
  parser.add_argument("--model","-m", help="read model from")
  parser.add_argument("--config","-c", help="read configuration from")
  parser.add_argument("--output","-o", type=argparse.FileType('w'), metavar="FILE", default=sys.stdout, help="output to FILE (default stdout)")
  args = parser.parse_args()

  try:
    load_config(args.config)
  except ValueError:
    write_blank_config(DEFAULT_CONFIG_FILE)
    parser.error('no configuration found. blank config written to: {0}'.format(DEFAULT_CONFIG_FILE))

  if len(args.abstracts) > 0:
    chunk = [ open(a) for a in args.abstracts ]
  else:
    chunk = [ open(a) for a in map(str.strip, sys.stdin) if a ]

  handle, store_path = tempfile.mkstemp()
  os.close(handle)

  print >>sys.stderr, "PIBOSO tagging for {0} files".format(len(chunk))

  with Timer() as prog_timer:
    with Timer() as t:
      if args.model:
        # path to model is specified
        print >>sys.stderr, "unpacking model from:", args.model
        features, spaces, L0_cl, L1_cl = load_model(args.model)
      else:
        print >>sys.stderr, "unpacking default model"
        features, spaces, L0_cl, L1_cl = load_default_model()
      print >>sys.stderr, "unpacking took {0:.2f}s".format(t.elapsed)

    # induce all the features for the new documents
    with Timer() as feat_timer:
      induce(chunk, store_path, features, spaces)
      print >>sys.stderr, "computing features took {0:.2f}s".format(feat_timer.elapsed)

    store = Store(store_path, 'r')

    with Timer() as cl_timer:
      L0_preds = []
      for feat, cl in zip(features, L0_cl):
        fm = store.get_FeatureMap('NewDocuments', feat)
        # We need to trim the fv as the feature space may have grown when we tokenized more documents.
        # Hydrat's design is such that new features are appended to the end of a feature space, so
        # we can safely truncate the feature map.
        train_feat_count = cl.metadata['train_feat_count']
        assert(train_feat_count <= fm.raw.shape[1])
        L0_preds.append( cl(fm.raw[:,:train_feat_count]) )

      L0_preds = sp.csr_matrix(np.hstack(L0_preds))
      L1_preds = L1_cl(L0_preds)
        
      print >>sys.stderr, "classification took {0:.2f}s ({1:.2f} inst/s)".format(cl_timer.elapsed, cl_timer.rate(L0_preds.shape[0]))

    cl_space = store.get_Space('ebmcat')
    instance_ids = store.get_Space('NewDocuments')

    writer = csv.writer(args.output)
    for inst_id, cl_id in zip(instance_ids, L1_preds.argmax(axis=1)):
      cl_name = cl_space[cl_id]
      writer.writerow((inst_id, cl_name))
    print >>sys.stderr, "wrote output to:", args.output.name

    print >>sys.stderr, "completed in {0:.2f}s ({1:.2f} inst/s)".format(prog_timer.elapsed, prog_timer.rate(L0_preds.shape[0]))

if __name__ == "__main__":
  main()