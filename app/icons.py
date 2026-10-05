"""Lucide icons (https://lucide.dev, ISC licence) from one same-origin SVG sprite: {{ icon("gavel") }} in a template."""
import re

from flask import url_for
from markupsafe import Markup, escape

NAME = re.compile(r"^[a-z0-9-]+$")


def icon(name, size=16, cls=""):
    """Decorative by default (aria-hidden): the text next to an icon, or an aria-label on its button, is the real name."""
    if not NAME.match(name):
        raise ValueError(f"bad icon name {name!r}")
    href = url_for("static", filename="icons/lucide.svg")
    return Markup(f'<svg class="icon {escape(cls)}" width="{int(size)}" height="{int(size)}" aria-hidden="true" focusable="false">'
                  f'<use href="{href}#{name}"></use></svg>')
