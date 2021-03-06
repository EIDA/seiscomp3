ql2sc manages the import of SC3 objects from one or several QuakeLink servers
into a SeisComP3 system in real time. Like :ref:`scimex` but contrary to
:ref:`scimport` the exchange of the SC3 objects is event based. This means no
messages will be exchanged until the exporting system has produced an event.

The user may control at various levels which information to import. Whenever
possible server-side filters should be preferred to reduce both the network
bandwidth consumption as well as the CPU and memory utilization on the local
machine.

.. _ql2sc_event_filter:

Server-side event filter
========================

QuakeLink provides a filter syntax similar to SQL-WHERE clauses which may be
used to filter interesting events on the server side:

.. code-block:: none

   clause    := condition[ AND|OR [(]clause[)]]
   condition := MAG|DEPTH|LAT|LON|PHASES|OTIME|UPDATED [op float|time]|[IS [NOT] NULL]
   op        := =|&gt;|&gt;=|&lt;|&lt;=|eq|gt|ge|lt|ge
   time      := %Y,%m,%d[,%H,%M,%S,%f]

E.g. the following filter string would select only those events with a minimum
magnitude of 6, detected by at least 10 stations and which are shallower than
100km:

.. code-block:: sql

   MAG >= 6.0 AND PHASES >= 10 AND DEPTH < 100

.. _ql2sc_object_filter:

Server-side object filter
=========================

QuakeLink provides a coarse object filter for the most relevant SC3 objects:

============ ==============================================================
Option       Impact
============ ==============================================================
picks        include picks
amplitudes   include amplitudes
arrivals     include origin arrivals
staMags      include origin station magnitudes
staMts       include moment tensor station contributions and phase settings
preferred    include only preferred origin and magnitude information
============ ==============================================================

.. _routing:

Local object filter and routing
===============================

Subsequent to the server-side filters a routing table defines which objects to
import and to which message group to send them. Depending on the SC3 modules
listening to the specified message groups an object may be further processed.
Typically no modules (other than :ref:`scmaster`) is connected to the
``IMPORT_GROUP`` so that objects send to this group are just stored to the
database. If an object should be discarded the special group identifier ``NULL``
may be used.

The routing table is defined as a comma-separated list of
``object name:group name`` pairs. Also the routing rules are inherited
recursively within the SC3 object tree. If no explicit rule exists for an object
the routing of its parent is evaluated up to the ``EventParameters`` root node.

Examples:

.. code-block:: none

   EventParameters:IMPORT_GROUP

Imports everything

.. code-block:: none

   EventParameters:IMPORT_GROUP,Comment:NULL

Imports everything except comments

.. code-block:: none

   Origin:LOCATION,StationMagnitude:MAGNITUDE,Magnitude:MAGNITUDE

Sends origins and it's children arrival, origin uncertainty to the ``LOCATION``
group but the magnitude children to the ``MAGNITUDE`` group. Skips picks,
amplitudes, focal mechanisms and events.

.. _agency_filter:

Agency list filter
==================

In addition to the local object filter the user may choose to accept only those
objects originating from a set of trusted agencies. If at least one agency is
defined in the ``processing.whitelist.agencies`` or
``processing.blacklist.agencies`` configuration option, then the
``creationInfo.agencyID`` of amplitudes, arrivals, comments, events, focal
mechanisms, magnitudes, moment tensors, origins, picks and station magnitudes is
evaluated. Objects with unmatched or unset agency information are filtered out.
If objects with unset agency id should match then empty string ``""`` has to be
added to the white list.

The agency filter is applied on remote as well as local objects. In this way
remote objects may be excluded from import and local objects my be protected
from overriding or removing. Also the filter is applied recursively. If parent
object (e.g. an origin) is filtered out all of its children (e.g. magnitudes)
are also skipped even if they carry a different agency id.

.. note::

   The agency white list filter might be essential to avoid circular event
   updates between cross-connected SC3 systems.


Workflow
========

Each event update received from a QuakeLink host is parsed and analyzed for
differences to the local database. The comparison starts at the level of the
top-level elements in the following order: picks, amplitudes, origins, focal
mechanisms, events.

For each top-level element the object tree is traversed in a depth-first search
order. Objects on the same level are processed in the order of their appearance.
The differences are collected as a list of notifier objects with the following
operation types:

====== ===========
Type   Description
====== ===========
ADD    The object does not exist locally
UPDATE The object does exist locally but differs from the remote one
REMOVE The object exist locally but not remotely
====== ===========

The ``ADD`` and ``REMOVE`` operation always generates notifies of the same type
for all children of the current object. ``ADD`` notifiers are collected top-down,
``REMOVE`` notifiers are collected bottom-up.

Because the order of child objects is arbitrary, e.g. the arrivals of an origin,
each object on the remote side has to be found in the set of local objects. For
public objects (e.g. origins, magnitudes, magnitudes..), the ``publicID`` property
is used for comparison. All other objects are compared by looking at their index
properties. For e.g. arrivals this is the ``pickID`` property, for comments the
``id`` property.

Ones all notifiers are collected they are send to the local messaging system.
For performance reasons and because of the processing logic of listening SC3
modules ql2sc tries to batch as many notifiers as possible into one notifier
message. A separate notifier message is created if the target message group
changes between successive notifiers or if the configurable :ref:`batchSize`
limit is reached.

.. note::

   Care must be taken when configuring the ``batchSize`` limit. If the value
   is to big the overall message size limit (default: 1MB) may be exceeded
   resulting in an undeliverable message. On the other hand a much to small
   value will create unwanted results in the SC3 processing chain. If for
   instances picks are routed to the ``PICK`` group and the pick set is split
   into several notifier messages the local :ref:`scautoloc` might create
   locations based on an incomplete dataset.


Caveats
=======

Specific combinations of remote and local object filters may result in the loss
of data. If for instance origins are imported from system ``A`` to ``B`` and
additional magnitudes for the received origins are calculated on ``B`` care must
be taken. Without protection a new event update containing the same origin will
``REMOVE`` all newly calculated magnitudes on ``B`` since they are not included
in the magnitude set sent by ``A``.

To avoid losing these local magnitudes one may decide to block magnitudes from
import by routing them to ``NULL``. If magnitudes from ``A`` and from ``B``
should be available an :ref:`agency filter<agency_filter>` may be defined. Make
sure ``A`` and ``B`` uses distinct agency IDs and add the agency ID of ``B`` to
``processing.blacklist.agencies``.

