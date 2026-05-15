"""
`shishenlu` — 式神录 plugin.

Owns the 式神录 (shikigami records) screen — entered from 庭院 by
expanding the right-bottom fold panel and clicking the entry button.
Currently a *scaffold* plugin: registers the inner-screen vertex so the
graph reaches 式神录, but has no gameplay loop yet. ``run()`` returns
immediately. Add real logic incrementally.

See README §5 for the new-plugin workflow this folder is the template
of.
"""

from plugins.shishenlu.plugin import ShishenluPlugin

__all__ = ["ShishenluPlugin"]
