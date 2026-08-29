#!/usr/bin/env python3
"""Exceptions shared across the acquisition layer.

Lives alone so acquire.py and article.py stop importing each other — article
needed AcquireError from acquire while acquire routes URLs to article, and the
cycle was only held at bay by a function-level import."""


class AcquireError(RuntimeError):
    """retryable=False means it can never succeed (deleted, private, no media),
    so the link is released instead of being retried on every restart."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable
