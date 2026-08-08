#!/usr/bin/env python3
"""Stable workflow entry point for normal-return M10 clone support.

This path is intentionally retained as the Actions trigger while the detailed
normal-return transform lives in augment_clone_compat_v6.py.
"""
from augment_clone_compat_v6 import main


if __name__ == "__main__":
    main()
