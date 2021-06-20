# copyright MIT rapptz discord.py


def add_custom_jinja2(app):
    env = app.builder.templates.environment
    env.tests["prefixedwith"] = str.startswith
    env.tests["suffixedwith"] = str.endswith


def setup(app):
    app.connect("builder-inited", add_custom_jinja2)
