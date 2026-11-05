# Touch entry, login and PLC identity

## Edit controls and limits

Drop **Numeric input** or **Text input** onto a screen or faceplate. Select a
writable tag and allowed HMI groups. Numeric edits offer fixed minimum/maximum
values and optional **Minimum from tag** / **Maximum from tag** bindings. Each
configured tag overrides its corresponding fixed value. Text edits provide
minimum/maximum character counts and optional numeric tag bindings for either
length limit. Text length tags must contain integers from 0 through 4096.

Limit tags use the screen's shared scan demand, including UDT-relative bindings.
The display uses good-quality cached values; stale, missing, nonnumeric or
reversed limits block entry. Python checks the current cached limits again before
dispatching every write. There is no fallback to fixed values when a configured
limit tag is unavailable. The PLC still owns process interlocks and final bounds
that must hold independently of HMI polling and communication timing.

Use **Open numeric keypad** or **Open keyboard** on an edit control. The modal
supports touch keys, backspace, clear, cancel and explicit acceptance. Physical
typing and native Unicode/IME entry remain available. The text keyboard provides
a US Latin layout with Shift, punctuation and Space. Password keyboard fields
are masked. Acceptance validates the latest limits and keeps the dialog open on
failure; cancel performs no write. Manual typed entry remains available too.

Character limits count Unicode code points, consistently in Python and the
browser, rather than UTF-16 units. PLC STRING byte capacities are a separate
constraint and can reject an otherwise valid character count. New example
projects include a writable local `OperatorText` tag. Existing projects are not
rewritten; create/select a suitable string tag in **Tags** when adding an edit.

## Login, current user and lock legend

**Open HMI login** opens a modal with local/Windows account selection and touch
keyboards for user name and password. Bootstrap the first administrator with the
existing console command. The **Current login user** control can be placed on any
screen; its button also opens the login dialog. `/api/security/session` remains
the server's current-user function for integrations. Browser SSO is separate work.

In **Security**, give each HMI group a **Group security color**. Locked action/edit
controls display lock symbols in the applicable group colors. Click or keyboard
activate the locked area to open a legend showing the color/group names and the
required operation permission. Command buttons also explain command-specific
group requirements separately. A permission is still required when a security
administrator overrides control-specific group membership. Colors convey access
categories, not alarm priority or a grant of permission. PLC enable conditions
are checked independently. Backend authorization remains decisive on every write.

Group colors persist with security configuration, new-project inheritance and
complete backups. Existing groups receive deterministic default colors until
edited; existing permissions are preserved.

## Optional PLC publication

Configure **PLC login** in the designer and Apply live. Saving a changed mapping
and applying a changed publication contract require `security.manage` as well as
project editing access. Publication is disabled by default. Configure:

* A writable, unscaled logical string tag pointing to the PLC STRING.
* A separate writable, unscaled integer tag pointing to the PLC DINT.
* Optional writable integer tag pointing to a separate heartbeat DINT.
* The username's UTF-8 byte capacity; identities are rejected rather than silently
  truncated when too long.
* Unique DINT bit positions 0–31, each mapped to an HMI permission or group name.

Logical tags may address suitable PLC UDT members. Native PLC metadata must
identify the username as STRING and the word/counter as DINT before publication.
Local logical tags support offline simulation. Bit 31 uses the corresponding
negative signed DINT representation; mask status is displayed as unsigned.

Grant `identity.publish` to groups authorized to claim the operator station.
Only newly created Administrators receive it initially. Existing groups require
an explicit grant. Sign in, then choose **Publish this station login**. One station
owns publication; a second station receives a conflict rather than replacing it.
An owning station can change authenticated users through the login dialog.
Other HMI clients keep their own sessions and permissions.

The browser renews a 15-second station lease every two seconds. The service
reevaluates the session, groups and permissions before publication. Logout,
session expiry, lease expiry or loss of publishing permission requests an empty
username and zero privileges. Publication is held for imported projects until
the configured PLC connections are deliberately released through Apply live.
The selected station is not restored after restarting or importing a project.

Status writes occur at most once per second while unchanged, with immediate
updates on observed identity changes. The word is written zero first, the user
name next, and the mapped privilege word last. The optional heartbeat advances
after a complete status update. These tags are reserved from ordinary edit/button
writes while publication is enabled. The status panel reports pending, clearing,
published, held or failed writes; failed idempotent status updates are retried.

The STRING and DINT are not an atomic pair. PLC logic must decide how to consume
them and detect stale communication. Use the heartbeat with a PLC-side timeout
when PLC behavior depends on a current login; a stopped HMI or broken connection
cannot clear PLC memory. This is status publication, not a safety function or a
replacement for PLC authorization/interlocks. Disable publication and wait for
cleared/disabled status before removing, retargeting or changing its tag definitions.

Local software tests use simulated tags and fake Logix metadata. Actual PLC
STRING capacities, metadata access, scan timing, communication-loss handling,
Windows/domain credentials and operator display behavior need target acceptance.
