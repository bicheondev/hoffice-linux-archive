#!/usr/bin/env python3
"""Stable workflow entry point for mature M10 clone support.

This path remains the Actions trigger.  The detailed transform now lives in
``augment_clone_compat_v7.py`` and adds the verified Darwin pthread TSD-base
capture required to restore GS correctly under Rosetta before libpthread
teardown.
"""
from augment_clone_compat_v7 import main


if __name__ == "__main__":
    main()
