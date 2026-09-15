"""Gunicorn access log without the secret tokens some URLs carry.

Calendar feeds, invitations and password resets are reached through links with a token in the
path. Anyone who can read the logs must not be able to reuse them.
"""

import re

from gunicorn.glogging import Logger

SECRET_SEGMENTS = [
    (re.compile(r"(/calendario/ics/)[^/?\s\"]+(\.ics)"), r"\1<token>\2"),
    (re.compile(r"(/hogar/invitacion/)[^/?\s\"]+"), r"\1<token>"),
    (re.compile(r"(/cuenta/contrasena/nueva/)[^/?\s\"]+/[^/?\s\"]+"), r"\1<token>"),
]


def redact(text):
    for pattern, replacement in SECRET_SEGMENTS:
        text = pattern.sub(replacement, text)
    return text


class RedactingLogger(Logger):
    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        for key in ("r", "U", "f"):  # request line, path and referer
            if isinstance(atoms.get(key), str):
                atoms[key] = redact(atoms[key])
        return atoms
