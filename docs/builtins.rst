
.. _builtins:

Built in functions
====================
This is a comprehensive list of every built in function, and the variables given to every automod action.

$savecase
----------
The ``savecase`` function allows you to manually create cases inside your actions.
See the :ref:`cases<Cases>` documentation.

Arguments
++++++++++
| 1: ``(number)`` The :ref:`ID<faq_userid>` of the user who this case should be saved for (The offender)
| 2: ``(number)`` The :ref:`ID<faq_userid>` of the moderator who preformed this action
| 3: ``(text)`` The reason this action was preformed
| 4: ``(text)`` The message link leading to the offending message
| 5: ``(text)`` The action preformed. This can be anything, however there are some :ref:`Built in moderation actions` that will be automatically used by other functions such as $ban

Returns
++++++++
``(number)`` The case number of the newly created case


$editcase
----------
Allows you to edit a previous case.
See the :ref:`cases<Cases>` documentation.

Arguments
++++++++++
| 1: ``(number)`` The case number to edit
| 2: ``(text)`` The newly updated reason
| 3: ``(text)`` [OPTIONAL] the newly updated action. This can be anything, however there are some :ref:`Built in moderation actions` that will be automatically used by other functions such as $ban

Returns
++++++++
``(number)`` The case number of the edited case


$usercases
-----------
Fetches all case numbers belong to the specified user id.

Arguments
++++++++++
1: ``(number)`` The :ref:`ID<faq_userid>` of the user to fetch cases for

Returns
++++++++
``(text)`` a space separated list of case ids


$pick
------
Returns a random argument

Arguments
++++++++++
Minimum of two arguments, they can be anything. Direct text should be ``'quoted'``

Returns
++++++++
``(any)`` Any of the arguments


$now
-----
Returns the current time in discord markdown format

Arguments
++++++++++
None

Returns
++++++++
``(text)`` A block of markdown text that looks like this: ``<t:1624095917:F>``


$send
------
Sends a message to a specific channel. Make sure the bot has permission to send messages to the channel

Arguments
++++++++++
| 1: ``(text, number)`` The name or id of the channel to send to. Direct text should be ``'quoted'``
| 2: ``(text)`` The text to send to the channel. Direct text should be ``'quoted'``

Returns
++++++++
Nothing


$mute
------
Applies the configured mute role to the target, creates a case, and dispatches the appropriate events and automod actions

Arguments
++++++++++
| 1: ``(number)`` The :ref:`ID<faq_userid>` of the user to mute
| 2: ``(text)`` [OPTIONAL] The reason for the mute
| 3: ``(text)`` [OPTIONAL] The duration to mute for. This can be in a time form ("for two days"), or a more concrete form ("saturday at 11 pm"). Times are in UTC

Returns
++++++++
``(text)`` A nicely formatted string: ``Muted User#0000``, or ``Muted User#0000 for 2 hours`` if a duration is provided


$kick
------
Kicks a user from the server, creates a case, and dispatches the appropriate events and automod actions

Arguments
++++++++++
| 1: ``(number)`` The :ref:`ID<faq_userid>` of the user to kick
| 2: ``(text)`` [OPTIONAL] The reason for the kick

Returns
++++++++
``(text)`` A nicely formatted string: ``Kicked User#0000``

$ban
-------
Bans a user from the server, creates a case, and dispatches the approprate events and automod actions

Arguments
++++++++++
| 1. ``(number)`` The :ref:`ID<faq_userid>` of the user to ban
| 2. ``(text)`` [OPTIONAl] The reason for the ban
| 3. ``(text)`` [OPTIONAL] The duration the ban should be. It will automatically be lifted after this time. Could be formatted like "3h" or "until january"

Returns
++++++++
``(text)`` A nicely formatted string: ``Banned User#0000``, or ``Banned User#0000 for 2 hours`` if a duration is provided

$addrole
---------
Adds a role to a member.

Arguments
++++++++++
| 1. ``(number)`` The :ref:`ID<faq_userid>` of the user to add the role to
| 2. ``(number)`` The :ref:`ID<faq_roleid>` of the role to add
| 3. ``(true/false)`` [OPTIONAL] Whether or not to persist the role if the user leaves and re-joins the server. Defaults to ``false``

Returns
++++++++
Nothing

$removerole
------------
Removes a role from a member. This will remove persistence (The role will no longer be added if the user re-joins the server)

Arguments
++++++++++
| 1. ``(number)`` The :ref:`ID<faq_userid>` of the user to remove the role from
| 2. ``(number)`` The :ref:`ID<faq_roleid>` of the role to remove

Returns
++++++++
Nothing

$coalesce
----------
A special function that takes any amount of arguments, and returns the first one that exists as a variable.
For example: ``$coalesce('user', 'userid')`` will return the value for ``user`` if a variable called ``user`` exists,
otherwise it will return the value for ``userid``, assuming it exists as well. If none of the given arguments exist,
it will return nothing.

Arguments
++++++++++
Any amount, all should be quoted text

Returns
++++++++
Could return anything

$match
-------
Checks if the first argument matches the second argument. If the first argument is a regex, the text will be searched
with the regex, otherwise the second argument must match the first one exactly.

Arguments
++++++++++
| 1. ``(text or regex)`` The text to match against the second argument. For more info on how to use regex, :ref:`Click Here<guide_regex>`
| 2. ``(text)`` The text to be searched.

Returns
++++++++
``(true/false)`` returns true if the text matched the first argument, otherwise returns false

$replace
---------
Replaces a snippet of text with another snippet.
For example: ``$replace('hello', 'hey hello hi', 'hi')`` would result in ``'hey hi hi'``.

Arguments
++++++++++
| 1. ``(text or regex)`` Where to replace in the input text. For more info on how to use regex, :ref:`Click Here<guide_regex>`
| 2. ``(text)`` The input text
| 3. ``(text)`` What to replace the target text with

Returns
++++++++
``(text)`` The input text with the text replaced

$capturetext
-------------
Stores the capture groups of a regex into variables that you can use later on.

Due to the order of parsing in this bot, you may use this function in an ``if`` block, and the variables will be available to your action, ex:

.. code-block:: toml

    { reply = "$grammar there, $user", if = "$capturetext(/(hi|bye)/, $content, 'grammar') == true" }

.. note::

    | You cannot overwrite existing variables with this function. Attempting to do so will result in an error.
    | To ignore a group, pass ``'_'`` as the variable name. You may do this as many times as you want.

Arguments
++++++++++
| 1. ``(regex)`` The regex to match to. This should have at least one capture group. For more info on how to use regex, :ref:`Click Here<guide_regex>`
| 2. ``(text)`` The text to be searched.
| Additional arguments: Each group needs an additional argument (in order of the groups) specifying the name for the variable.

Returns
++++++++
``(bool)`` Whether any text was found or not. If your regex did not match, this returns ``false``, otherwise it returns ``true``

.. _builtin_caseactions:

Built in moderation actions
============================
- mute
- tempmute (temporary mute)
- unmute
- kick
- ban
- tempban (temporary ban)
