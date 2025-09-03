Airflow 2.11.0 (2025-05-20)
---------------------------

Significant Changes
^^^^^^^^^^^^^^^^^^^

``DeltaTriggerTimetable`` for trigger-based scheduling (#47074)
"""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

This change introduces DeltaTriggerTimetable, a new built-in timetable that complements the existing suite of
Airflow timetables by supporting delta-based trigger schedules without relying on data intervals.

Airflow currently has two major types of timetables:
    - Data interval-based (e.g., ``CronDataIntervalTimetable``, ``DeltaDataIntervalTimetable``)
    - Trigger-based (e.g., ``CronTriggerTimetable``)

However, there was no equivalent trigger-based option for delta intervals like ``timedelta(days=1)``.
As a result, even simple schedules like ``schedule=timedelta(days=1)`` were interpreted through a data interval
lens—adding unnecessary complexity for users who don't care about upstream/downstream data dependencies.

This feature is backported to Airflow 2.11.0 to help users begin transitioning before upgrading to Airflow 3.0.

    - In Airflow 2.11, ``schedule=timedelta(...)`` still defaults to ``DeltaDataIntervalTimetable``.
    - A new config option ``[scheduler] create_delta_data_intervals`` (default: ``True``) allows opting in to ``DeltaTriggerTimetable``.
    - In Airflow 3.0, this config defaults to ``False``, meaning ``DeltaTriggerTimetable`` becomes the default for timedelta schedules.

By flipping this config in 2.11, users can preview and adopt the new scheduling behavior in advance — minimizing surprises during upgrade.


Consistent timing metrics across all backends (#39908, #43966)
""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""

Previously, Airflow reported timing metrics in milliseconds for ``StatsD`` but in seconds for other backends
such as ``OpenTelemetry`` and ``Datadog``. This inconsistency made it difficult to interpret or compare
timing metrics across systems.

Airflow 2.11 introduces a new config option:

  - ``[metrics] timer_unit_consistency`` (default: ``False`` in 2.11, ``True`` and dropped in Airflow 3.0).

When enabled, all timing metrics are consistently reported in milliseconds, regardless of the backend.

This setting has become mandatory and always ``True`` in Airflow 3.0 (the config will be removed), so
enabling it in 2.11 allows users to migrate early and avoid surprises during upgrade.

Ease migration to Airflow 3
"""""""""""""""""""""""""""
This release introduces several changes to help users prepare for upgrading to Airflow 3:

  - All models using ``execution_date`` now also include a ``logical_date`` field. Airflow 3 drops ``execution_date`` entirely in favor of ``logical_date`` (#44283)
  - Added ``airflow config lint`` and ``airflow config update`` commands in 2.11 to help audit and migrate configs for Airflow 3.0. (#45736, #50353, #46757)

Python 3.8 support removed
""""""""""""""""""""""""""
Support for Python 3.8 has been removed, as it has reached end-of-life.
Airflow 2.11 requires Python 3.9, 3.10, 3.11, or 3.12.

New Features
""""""""""""

- Introduce ``DeltaTriggerTimetable`` (#47074)
- Backport ``airflow config update`` and ``airflow config lint`` changes to ease migration to Airflow 3 (#45736, #50353)
- Add link to show task in a DAG in DAG Dependencies view (#47721)
- Align timers and timing metrics (ms) across all metrics loggers (#39908, #43966)

Bug Fixes
"""""""""

- Don't resolve path for DAGs folder (#46877)
- Fix ``ti.log_url`` timestamp format from ``"%Y-%m-%dT%H:%M:%S%z"`` to ``"%Y-%m-%dT%H:%M:%S.%f%z"`` (#50306)
- Ensure that the generated ``airflow.cfg`` contains a random ``fernet_key`` and ``secret_key`` (#47755)
- Fixed setting ``rendered_map_index`` via internal api (#49057)
- Store rendered_map_index from ``TaskInstancePydantic`` into ``TaskInstance`` (#48571)
- Allow using ``log_url`` property on ``TaskInstancePydantic`` (Internal API) (#50560)
- Fix Trigger Form with Empty Object Default (#46872)
- Fix ``TypeError`` when deserializing task with ``execution_timeout`` set to ``None`` (#46822)
- Always populate mapped tasks (#46790)
- Ensure ``check_query_exists`` returns a bool (#46707)
- UI: ``/xcom/list`` got exception when applying filter on the ``value`` column (#46053)
- Allow to set note field via the experimental internal api (#47769)

Miscellaneous
"""""""""""""

- Add ``logical_date`` to models using ``execution_date`` (#44283)
- Drop support for Python 3.8 (#49980, #50015)
- Emit warning for deprecated ``BaseOperatorLink.get_link`` signature (#46448)

Doc Only Changes
""""""""""""""""
- Unquote executor ``airflow.cfg`` variable (#48084)
- Update ``XCom`` docs to show examples of pushing multiple ``XComs`` (#46284, #47068)