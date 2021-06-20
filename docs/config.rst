
.. _config:

Configuration Files
====================

Data Types
-----------

Strings
++++++++
TODO

Actions
--------
TODO

Cases
------
TODO

Conditionals
-------------
When creating an :ref:`action<Actions>`, you may want to specify conditions for it to execute.
You can do this by providing an ``if`` parameter to the action.

For example, the following event will only dispatch ``otherevent`` if the ``userid`` variable is equal to
``547861735391100931``.

.. code-block:: toml

    [[event]]
    name = "myevent"
    actions = [
        { dispatch = "otherevent", if = "$userid == 547861735391100931" }
    ]

This of course assumes that this event is given a ``userid`` variable, otherwise it will raise an error, similar to this:

.. code-block:: text

    at <dispatch>
    ...
    at event 'myevent'
    at action #0 (type: dispatch)
    at <conditional>
    ~~~
    | $userid == 547861735391100931
    | ^^^^^^^
    | Variable 'userid' not found in this context

Conditionals are **strict**, meaning that unlike other parsed text, conditionals will not allow unknown text.
For example, the following config will raise an error while being parsed.

.. code-block:: toml

    [[event]]
    name = "myevent"
    actions = [
        { dispatch = "otherevent", if = "say hi $userid" }
    ]
