
.. _guide:

A quick introduction
====================

This guide is meant to help you through the complexities of this bot,
showing you how you can combine different aspects to create something that fits your
moderation needs. This bot is unique in it's use of file-based configuration,
which may seem over-complex, but allows for extreme flexibility you just can't get
from configuring in discord itself.

Core configurations
===================

| The format used for configuration files is `Toml <https://github.com/toml-lang/toml/blob/master/toml.md>`_.
| Every config needs an error channel, which is where the bot will send parsing errors if your config encounters an error.

We can set one like this:

.. code-block:: toml

    error-channel = "#error-channel"

What's important to note here is that a channel reference can be any of the following:

- A quoted channel name
- A channel id

When using quotes, we tell toml that this is text, not a number or a boolean (true/false).
When providing a channel name, we can provide it as ``#error-channel`` or ``error-channel``, they both mean the same thing.
You should make sure you don't have multiple channels with the same name as the one you use when referencing a channel like this.
If you want to have multiple channels with the same name, you should consider passing the channel id instead.
This can be obtained by enabling developer mode (settings -> Advanced -> Developer Mode), right clicking on the channel,
and pressing ``Copy ID``. If we were to use this instead, our error-channel would look something like

.. code-block:: toml

    error-channel = 843972155166949377

Now, the other thing a config needs is at least one event. An event is a collection of actions that can be dispatched
based on certain conditions. If you've done programming, you can think of it as a sort of function. When you call an event,
all the variables from wherever you call it from are passed along, plus anything you define in the ``args`` (more on that later).
Let's take a quick look at simple, empty event:

.. code-block:: toml

    [[event]]
    name = "warn"
    actions = []

Now what's going on with these braces, you might be wondering. The spec is officially described `here <https://github.com/toml-lang/toml/blob/master/toml.md#array-of-tables>`_,
but for here we'll say that the double braces tell the parser that we're creating a new event.
Everything below that set of double braces is part of that event, until we get to the next set of them.
Every event needs a name, so that it can be called by other things in your config. What's important to know is that
you can only have **one** of each name. They have to be unique!

Next let's look at the ``actions``. All it has is a set of braces, which means the event doesn't actually *do* anything.
We'll come back to this once we set up actions for the event to call. But for now, let's put our ``error-channel`` and our ``event`` together
to make a working config:

.. code-block:: toml

    error-channel = 843972155166949377

    [[event]]
    name = "warn"
    actions = []


Events
=======

As described above, events are similar to functions in programming. You can call them from almost wherever.
Let's define two events, with one calling the other:

.. code-block:: toml

    [[event]]
    name = "warn"
    actions = [
        { dispatch = "kick" }
    ]

    [[event]]
    name = "kick"
    actions = [

    ]

Ok, we've introduced the funky looking brackets here. What are those doing? The spec can be found `here <https://github.com/toml-lang/toml/blob/master/toml.md#inline-table>`_,
but for our case, it'll suffice to say that you're creating an instruction.
Now whenever ``warn`` gets dispatched (called), it'll subsequently dispatch ``kick``, which does... absolutely nothing.
So let's make the ``kick`` event kick the person!

.. code-block:: toml

    [[event]]
    name = "warn"
    actions = [
        { dispatch = "kick" }
    ]

    [[event]]
    name = "kick"
    actions = [
        { do = "$kick($userid, 'you've been kicked')" }
    ]

wow ok, there's a lot going on here. Variables will be discussed below, for now we'll focus on what's going on here.
When something dispatches the ``warn`` event, it in turn dispatches the ``kick`` event, which proceeds to kick the user
with the given $userid. Which means that we have to pass a ``userid`` variable to ``kick``. But what happens if we don't get
a ``userid`` variable? Well, the parser will send an error to your error channel telling you what went wrong. It'll look
something like this:

.. code-block:: text

    at <dispatch>
    at event 'warn'
    at action #0 (type: dispatch)
    at event 'kick'
    at action #0 (type: do)
    at 'do'
    ~~~
    | $kick($userid, 'you've been kicked')
    |       ^^^^^^^
    | Variable 'userid' not found in this context

The parser has pointed us down the chain of events, right to the problem.
Let's say that we've been given a ``targetid`` variable, that contains the id of the person we want to warn.
We need to turn that ``targetid`` into ``userid`` for the kick event. Here's how we can do that:

.. code-block:: toml

    [[event]]
    name = "warn"
    actions = [
        { dispatch = "kick", args = { userid = "$targetid" } }
    ]

    [[event]]
    name = "kick"
    actions = [
        { do = "$kick($userid, 'you've been kicked')" }
    ]

This tells the parser to create a variable called ``userid`` that is equal to the ``targetid`` variable. ###### CONTINUE FROM HERE ######

Counters
========

Let's say we want to track how many w


.. _guide_regex:

Regex
======
todo
