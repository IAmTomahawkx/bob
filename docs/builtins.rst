
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
``(int)`` The case number of the newly created case


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
``(int)`` The case number of the edited case


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
| 1: ``(number)`` The :ref:`ID<faq_userid>` of the user to mute
| 2: ``(text)`` [OPTIONAL] The reason for the mute
| 3: ``(text)`` [OPTIONAL] The duration to mute for. This can be in a time form ("for two days"), or a more concrete form ("saturday at 11 pm"). Times are in UTC

Returns
++++++++
``(text)`` A nicely formatted string: ``Muted User#0000``, or ``Muted User#0000 for 2 hours`` if a duration is provided



.. _builtin_caseactions:

Built in moderation actions
============================
- mute
- tempmute (temporary mute)
- unmute
- kick
- ban
- tempban (temporary ban)
