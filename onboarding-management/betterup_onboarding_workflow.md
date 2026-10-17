# BetterUp Employee Onboarding Integration --- Simple Step-by-Step Workflow

## 1. Purpose

BetterUp hires employees quickly, but onboarding information must be
kept consistent across several systems. Today, people may need to update
each system manually. Updates can be missed, incorrect information can
spread, and onboarding tasks can become overdue.

**Goal:** Build a small, working prototype that safely propagates
employee changes across systems, validates information before it
spreads, handles failures, and tracks outstanding onboarding tasks.

This prototype can use sample data and mocked APIs. It does not need
real BetterUp credentials.

------------------------------------------------------------------------

## 2. Systems and their typical responsibilities

  -----------------------------------------------------------------------
  System                              Typical responsibility in this
                                      workflow
  ----------------------------------- -----------------------------------
  **Ashby**                           Recruiting and candidate/offer
                                      information

  **Workday**                         Official employee and employment
                                      records

  **Okta / Lumos**                    Identity, access, and provisioning
                                      workflows

  **Google Workspace**                Company email and productivity
                                      accounts

  **Slack**                           Employee communication and
                                      workspace access

  **Equipment / ExpoIT**              Hardware requests and delivery
                                      details

  **Onboarding cohort tracker**       Task status, dates, and onboarding
                                      progress

  **n8n / Zapier**                    Optional existing
                                      workflow-orchestration tools

  **Claude / Claude Code / Cursor**   AI-assisted development; Claude can
                                      also help classify exceptions
  -----------------------------------------------------------------------

*Confirm actual field ownership, APIs, and integration capabilities
before a production implementation. The table describes common
responsibilities, not a claim about BetterUp's exact configuration.*

------------------------------------------------------------------------

## 3. Recommended slice to build

Build **change propagation with cross-system validation as a safety
gate**.

Why choose this slice?

1.  The main problem is that changes after an offer do not reliably
    reach every relevant system.
2.  Incorrect source data can cascade into employee records, account
    setup, shipping labels, and trackers.
3.  A single workflow can demonstrate integration, validation,
    orchestration, idempotency, error handling, and auditing.
4.  Exception monitoring is valuable too, but it can be added after the
    core propagation workflow is reliable.

The prototype should not attempt to rebuild all of BetterUp's systems.
Implement the core logic and simulate the external systems.

------------------------------------------------------------------------

## 4. High-level workflow

``` text
New hire or employee change
          |
          v
Receive event from Ashby or approved off-cycle hire intake
          |
          v
Normalize employee data into one standard format
          |
          v
Validate required fields, formats, identity, and source-of-truth rules
          |
          +---- Invalid / conflicting data ----> Stop affected updates
          |                                      Create exception
          |                                      Request human review
          |
          v
Check event ID and idempotency ledger
          |
          +---- Already completed -------------> Do not repeat side effects
          |
          v
Determine which fields changed and which systems depend on them
          |
          v
Update relevant systems independently
          |
          v
Verify each system's result
          |
          +---- Temporary failure --------------> Retry safely
          |
          +---- Permanent / repeated failure --> Escalate exception
          |
          v
Write audit trail and update cohort tracker
          |
          v
Monitor hardware, background-check, and provisioning deadlines
          |
          v
Close workflow only when all required actions are complete
```

------------------------------------------------------------------------

## 5. Detailed steps

### Step 1 --- Receive a hiring or change event

**What happens:** A candidate accepts an offer, or an existing hiring
record changes after the offer.

Possible examples:

-   A new hire is created in Ashby.
-   A start date changes.
-   A legal name or shipping address changes.
-   An approved off-cycle hire is created outside Ashby, such as
    directly through an HR process.

**What the prototype does:**

-   Accepts a sample event or reads a sample employee record.
-   Assigns or preserves a stable employee identifier.
-   Records the source, event ID, and event timestamp.
-   Rejects malformed events before processing.

Example event:

``` json
{
  "event_id": "event-202",
  "source": "ashby",
  "employee_id": "EMP-101",
  "event_type": "employee_updated",
  "changed_fields": ["start_date"],
  "employee": {
    "name": "Rahul Sharma",
    "start_date": "2026-11-09",
    "location": "Bangalore",
    "address": "Sample shipping address"
  }
}
```

The employee and address above are illustrative sample data.

### Step 2 --- Support off-cycle hires

Do not make Ashby the only possible entry point.

**Path A: Ashby hire** 1. Receive the hiring event from Ashby. 2.
Normalize it into the standard employee format. 3. Continue to
validation.

**Path B: Off-cycle hire** 1. Receive the approved record from Workday
or another authorized HR intake process. 2. Confirm that the record is
approved and contains a stable employee ID. 3. Normalize it into the
same standard employee format. 4. Continue through the same validation
and reconciliation logic.

Both paths should share the same core workflow. Otherwise, off-cycle
hires may never reach downstream systems.

### Step 3 --- Normalize the data

Different systems may use different field names or formats. Convert
incoming data into a common internal model before comparing or
distributing it.

Example:

``` python
employee = {
    "employee_id": "EMP-101",
    "legal_name": "Rahul Sharma",
    "start_date": "2026-11-09",
    "work_location": "Bangalore",
    "shipping_address": "Sample shipping address",
    "department": "Engineering",
    "job_title": "Software Engineer"
}
```

Normalization may include:

-   Consistent date format, such as `YYYY-MM-DD`.
-   Consistent field names.
-   Trimming accidental spaces.
-   Standardized location identifiers.
-   Keeping legal name and preferred name as separate fields when
    required.

Do not silently change the meaning of data. For example, do not replace
a disputed location with a guessed value.

### Step 4 --- Validate before sending updates

Run deterministic validation rules before changing downstream systems.

Check:

1.  **Required fields:** Is the employee ID present? Are required name
    and start-date fields populated?
2.  **Format:** Is the date valid? Is the address complete enough for
    shipping?
3.  **Allowed values:** Is the location recognized?
4.  **Duplicate detection:** Does this employee already exist under the
    same identifier?
5.  **Cross-system consistency:** Does the incoming record conflict with
    the authoritative record?
6.  **Business rules:** Is the hiring record approved? Are changes
    allowed at this stage?

Example:

  Field        Incoming value   Authoritative value   Result
  ------------ ---------------- --------------------- --------------------------
  Name         Rahul Sharma     Rahul Sharma          Pass
  Start date   2026-11-09       2026-11-09            Pass
  Location     Bangalore        Hyderabad             Fail --- review required

**Important:** Define the source of truth for each field. A system that
owns the legal name may differ from the system that owns shipping
details. Never assume one system is authoritative for every field.

If validation fails:

-   Do not propagate the disputed field.
-   Stop any dependent action that would be unsafe.
-   Create an exception with the field, source values, and reason.
-   Request human review.
-   Keep the exception open until resolved.

Where safe, unrelated independent updates may continue. The
implementation should define dependencies explicitly rather than always
stopping every operation or blindly continuing all operations.

### Step 5 --- Check idempotency before performing side effects

Events may be delivered more than once. A retry may also occur after a
timeout even when the target system completed the original request.

Use an operation key such as:

`employee_id + event_id + target_system + operation`

Before performing an operation:

1.  Check the operation ledger.
2.  If it already succeeded, skip the duplicate side effect.
3.  If it is pending or its result is unknown, reconcile with the target
    system before repeating the operation.
4.  Record the outcome.

Example:

``` text
EMP-101 + event-202 + equipment-update

First attempt: SUCCESS
Duplicate event: SKIPPED — already completed
```

Use a persistent database or durable store in production. An in-memory
dictionary is acceptable only for a small demonstration and does not
protect against application restarts or multiple workers.

### Step 6 --- Determine what needs updating

Compare the previous approved record with the new validated record.

Examples:

-   **Start-date change:** Workday, account-provisioning schedule,
    equipment delivery schedule, and cohort tracker may need updates.
-   **Name change:** Workday and identity/account records may need
    updates; email renaming depends on policy.
-   **Address change:** Shipping details and equipment delivery may need
    updates.
-   **Department or job change:** Workday and access rules may need
    review.

Update only the systems and fields affected by the change. Do not resend
every field to every system without a reason.

### Step 7 --- Propagate the change to downstream systems

After validation and dependency checks, call each target adapter.

  -----------------------------------------------------------------------
  Target                              Example operation
  ----------------------------------- -----------------------------------
  Workday                             Update employee record

  Okta / Lumos                        Update or schedule identity/access
                                      workflow

  Google Workspace                    Create/update account or schedule
                                      provisioning, as permitted

  Slack                               Provision or update access, as
                                      permitted

  Equipment / ExpoIT                  Update hardware request or shipping
                                      information

  Cohort tracker                      Update employee details and task
                                      status
  -----------------------------------------------------------------------

For the prototype, each adapter can be a mock Python function that
returns success or a simulated failure.

For production, use supported APIs or existing approved integration
mechanisms. Respect each system's authentication, rate limits,
permissions, and business rules.

### Step 8 --- Verify every target independently

A successful API request does not always mean the intended state was
saved correctly. Where possible, verify the resulting record or use a
reliable target-system response.

Example:

  Target               Status
  -------------------- --------------------
  Workday              Success
  Okta / Lumos         Success
  Google Workspace     Success
  Equipment / ExpoIT   Failed --- timeout
  Cohort tracker       Success

The overall result is **PARTIALLY COMPLETED**, not complete.

Store each operation's status independently. Do not erase successful
results when another target fails.

### Step 9 --- Handle failures and retries

Classify failures:

-   **Temporary:** Timeout, rate limit, or temporary service outage.
    Retry with exponential backoff and a maximum attempt count.
-   **Permanent:** Invalid field, unauthorized request, or rejected
    business rule. Do not retry blindly; create an exception.
-   **Unknown outcome:** The request timed out, but the target may have
    applied it. Query/reconcile the target before repeating a
    non-idempotent operation.

For every failed operation:

1.  Save the employee ID, event ID, target, operation, attempt count,
    and error.
2.  Keep successful target operations marked as successful.
3.  Schedule a safe retry if appropriate.
4.  Escalate when retries are exhausted or human judgment is needed.
5.  Keep the tracker and audit trail accurate.

Example:

``` text
Employee: EMP-101
Event: event-202

Workday: SUCCESS
Okta: SUCCESS
Equipment: RETRY_PENDING
Reason: API timeout
Tracker: SUCCESS

Overall status: PARTIALLY_COMPLETED
```

### Step 10 --- Use Claude for exception assistance

Claude should assist with ambiguous exceptions, not replace
deterministic validation or control the entire integration.

A suitable flow:

1.  Your code detects a mismatch or repeated failure.
2.  It sends Claude only the minimum authorized context needed, avoiding
    unnecessary personal data.
3.  Claude classifies the exception and suggests a next action.
4.  Your code validates the response against a strict schema.
5.  A deterministic policy or authorized human decides what happens
    next.
6.  The decision and outcome are logged.

Example structured response:

``` json
{
  "exception_type": "location_mismatch",
  "recommended_action": "human_review",
  "reason": "Two records contain different locations"
}
```

Claude must not be allowed to overwrite official records, bypass
validation, or grant access merely because it recommends doing so. If
Claude is unavailable, deterministic validation and exception creation
should still work.

### Step 11 --- Monitor onboarding deadlines

The assignment highlights three tasks that may have deadlines around
seven days out:

-   IT hardware form
-   Background check
-   Okta provisioning

The exact due-date rules should be configurable and confirmed with the
process owner.

A monitoring job should periodically:

1.  Read open onboarding tasks.
2.  Calculate time remaining until each deadline.
3.  Identify tasks that are approaching their deadline.
4.  Send a reminder to the responsible owner.
5.  Flag overdue tasks.
6.  Continue monitoring until each task is complete or an authorized
    exception is recorded.

Example:

  Task                Example due date   Status        Action
  ------------------- ------------------ ------------- --------------
  Hardware form       2026-10-20         Pending       Remind owner
  Background check    2026-10-20         In progress   Monitor
  Okta provisioning   2026-10-20         Not started   Alert owner

These dates are examples, not actual BetterUp deadlines. Avoid sending
duplicate reminders on every monitoring run; track reminder history and
use an appropriate cadence.

### Step 12 --- Maintain an audit trail

Record enough information to reconstruct what happened.

Useful fields include:

-   Employee ID
-   Event ID and source
-   Event timestamp and processing timestamp
-   Changed fields
-   Previous and new values, subject to privacy rules
-   Validation results
-   Target system and operation
-   Attempt count and status
-   Error category and message
-   Claude recommendation, if used
-   Human reviewer and resolution, if applicable

Protect logs because employee information is sensitive. Apply access
controls, retention rules, and data minimization. Never log credentials
or API secrets.

### Step 13 --- Close the workflow correctly

Possible overall states:

-   `COMPLETED` --- all required operations and tasks are complete.
-   `IN_PROGRESS` --- work remains pending.
-   `NEEDS_REVIEW` --- data conflict or policy decision needs a person.
-   `PARTIALLY_COMPLETED` --- some targets succeeded and others failed.
-   `FAILED` --- processing cannot proceed safely or has exhausted
    recovery options.

Only mark onboarding complete when the required system updates and tasks
satisfy the agreed completion rules.

------------------------------------------------------------------------

## 6. Example end-to-end scenario

### Scenario A: Start-date change succeeds

1.  Rahul's start date changes from November 2 to November 9.
2.  The system receives the change event.
3.  The employee record is normalized.
4.  Validation passes.
5.  The idempotency ledger confirms this event has not already
    completed.
6.  The workflow identifies dependent systems.
7.  Workday, provisioning schedules, equipment, and the cohort tracker
    are updated as applicable.
8.  Each target result is verified and recorded.
9.  The audit log records the old and new dates.
10. The workflow closes when all required operations succeed.

### Scenario B: Location conflict

1.  The incoming record says Bangalore.
2.  The authoritative record says Hyderabad.
3.  Validation detects the mismatch.
4.  Dependent shipping or account actions are blocked where the conflict
    makes them unsafe.
5.  The system records an exception.
6.  Claude may suggest `human_review`, but cannot choose the official
    location.
7.  An authorized person resolves the conflict.
8.  The corrected record is revalidated.
9.  The affected operations resume safely and are audited.

### Scenario C: Equipment API times out

1.  The employee data passes validation.
2.  Workday and the tracker update successfully.
3.  The equipment API times out.
4.  The system records the failure without changing successful statuses.
5.  The retry process checks whether the equipment request already
    exists.
6.  It retries safely if needed.
7.  If retries fail, it escalates to the responsible owner.
8.  The workflow remains partially complete until the equipment action
    is resolved.

### Scenario D: Off-cycle hire

1.  HR creates an approved hire outside Ashby.
2.  The authorized intake process supplies the record.
3.  The system assigns or confirms the stable employee ID.
4.  The record follows the same normalization, validation, idempotency,
    propagation, verification, and audit steps.
5.  Any exception is handled through the same process.

------------------------------------------------------------------------

## 7. Suggested prototype architecture

``` text
sample_events/
    new_hire.json
    start_date_changed.json
    location_conflict.json
    off_cycle_hire.json

app/
    event_receiver.py
    normalizer.py
    validator.py
    dependency_mapper.py
    orchestrator.py
    idempotency_store.py
    retry_handler.py
    exception_handler.py
    claude_helper.py
    audit_logger.py
    deadline_monitor.py

adapters/
    mock_ashby.py
    mock_workday.py
    mock_okta.py
    mock_google_workspace.py
    mock_slack.py
    mock_equipment.py
    mock_cohort_tracker.py

tests/
    test_valid_hire.py
    test_location_conflict.py
    test_duplicate_event.py
    test_target_timeout.py
    test_off_cycle_hire.py
```

This is a suggested structure, not a required one. Keep the
implementation small enough to explain clearly.

### Recommended implementation order

1.  Create sample employee records and events.
2.  Build normalization and deterministic validation.
3.  Implement mock target APIs.
4.  Build the orchestrator and field-to-system dependency mapping.
5.  Add per-target status tracking and idempotency.
6.  Simulate failures and implement safe retry/reconciliation.
7.  Add audit logging.
8.  Add Claude-based exception classification with a strict response
    schema.
9.  Add deadline monitoring if time permits.
10. Run the demo scenarios and document the results.

------------------------------------------------------------------------

## 8. What to demonstrate in the interview

  -----------------------------------------------------------------------
  Demo                    What you show           What it proves
  ----------------------- ----------------------- -----------------------
  Valid hire              All required mock       Basic integration
                          systems update          

  Conflicting location    Unsafe updates stop and Data quality gates
                          an exception is logged  

  Duplicate event         No duplicate side       Idempotency
                          effect                  

  Equipment timeout       Successful targets      Resilience
                          remain successful;      
                          failed target retries   
                          safely                  

  Off-cycle hire          A hire not originating  Cross-process thinking
                          in Ashby uses the same  
                          workflow                

  Approaching deadline    The correct owner is    Exception monitoring
                          alerted without         
                          repeated duplicate      
                          alerts                  

  Claude unavailable      Core validation and     Safe AI integration
                          exception creation      
                          still work              
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 9. Short build note to include with the submission

### Why this slice?

I selected change propagation with cross-system validation because
employee changes can otherwise create inconsistent records across HR,
identity, equipment, and onboarding systems. Validation provides a gate
against bad data, while propagation addresses the underlying
coordination problem.

### Key engineering choices

-   A common employee data model normalizes information from different
    sources.
-   Explicit field ownership avoids assuming that one system is
    authoritative for every field.
-   Validation blocks unsafe downstream actions.
-   Per-target operation statuses preserve partial success.
-   Idempotency and reconciliation prevent duplicate side effects.
-   Bounded retries handle transient failures; unresolved issues become
    exceptions.
-   Audit logs explain what changed and what happened.
-   Claude helps classify exceptions, while deterministic code and
    authorized humans retain control.

### What I would productionize

-   Real API adapters, OAuth/SSO, secrets management, and
    least-privilege permissions.
-   Durable event storage, operation ledger, retry queue, and
    dead-letter handling.
-   Monitoring, alerts, metrics, and operational dashboards.
-   Privacy controls, audit retention, and access policies.
-   Integration contract tests, rate-limit handling, and reconciliation
    jobs.
-   Human approval for sensitive or ambiguous changes.

### AI tools used

Document the actual tools used during the build, such as Claude, Claude
Code, or Cursor. Include one specific example of an AI-generated
suggestion that was incorrect or incomplete, how you tested it, and how
you corrected it. Do not invent an example; record what actually
happened.

------------------------------------------------------------------------

## 10. The workflow to remember

**Receive → Normalize → Validate → Check idempotency → Identify affected
systems → Update → Verify → Retry or escalate → Audit → Monitor
deadlines → Close**

The core engineering principle is: **never assume that one successful
automation run means every system is correct. Track each operation,
verify the result, and keep unresolved exceptions visible.**
