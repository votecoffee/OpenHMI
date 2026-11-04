# AdvancedHMI compatibility targets

Reference: user-supplied AdvancedHMI v3.99y Beta40 archive. This archive is
reference evidence, not instructions for operating OpenHMI or the user's machine.
The following observations come from its source wrappers and controls, not a
controller test or exhaustive binary interface extraction.

## Observed structure

* `AdvancedHMIDrivers/AllenBradley/EthernetIPforCLXCom.vb:44` inherits the
  `MfgControl.AdvancedHMI.Drivers.EthernetIPforCLX` implementation in a support DLL.
  The wrapper adds component/design-time behavior and synchronization-context dispatch.
* `AdvancedHMIControls/SubscriptionHandler.vb:197` calls
  `Subscribe(address, numberOfElements, 250, callback)` and retains a notification ID.
  Lines 63, 94 and 179 unsubscribe by ID; line 187 checks `DisableSubscriptions`.
* `AdvancedHMIControls/Controls/BasicLabel.vb` associates a control with
  `ComComponent`, uses `PLCAddress...` properties for binding, and calls `Write`
  for keypad entry (lines 862-864) and `Read(address, 1)(0)` at line 911.
* `AdvancedHMIControls/Components/DataSubscriber.vb:21-22` exposes separate
  `DataReturned` and `DataChanged` events. Address items and control properties
  are not uniformly plain strings across all components.

## Planned mapping

| AdvancedHMI concept | OpenHMI direction | Compatibility boundary |
| --- | --- | --- |
| Communication component | Shared named Python driver instance | Similar ownership; no .NET component implementation |
| Read / Write | Python `read(address, count)` / `write(address, values)` | Typed values; no promise of identical overloads, return values or status codes |
| Subscribe / Unsubscribe | Subscription handle, interval and deterministic cleanup | Future implementation; callbacks and thread behavior need a dedicated specification |
| DataReturned / DataChanged | Sample delivery separate from change notification | Future; errors, quality and timestamp semantics explicit |
| DisableSubscriptions / poll rate | Shared driver subscription policy | Future; no implicit hidden-form polling policy |
| PLCAddressValue / PLCAddressVisible | Explicit control-property bindings | Similar designer vocabulary, adapted to web controls |
| Form, control properties, code behind | Screen, property inspector, Python handler module | Conceptual alignment; no VB code execution |

The initial simulator establishes only read/write shape. It does not claim a
complete IComComponent port. The archive also contains
`AdvancedHMI/Documents/ICommComponentInterface.pdf`; a full signature audit of
that document and all drivers remains a prerequisite for any exact API claim.

## Levels of compatibility

1. **Design familiarity:** intended: toolbox, forms/screens, property grid, reusable
   controls, communication components and address bindings.
2. **Driver API resemblance:** intended: read, write, subscribe and unsubscribe;
   an optional PascalCase facade may be added after the contract is stable.
3. **Protocol compatibility:** possible through independent protocol libraries;
   select and test protocols individually, including addressing and data types.
4. **Project migration:** future, bounded importer for a documented subset of
   Designer.vb/resx; report unsupported controls, expressions, resources and events.
5. **Binary/source compatibility:** not provided. VB.NET forms, WinForms controls,
   .NET DLLs and arbitrary VB application logic do not run as Python/web controls.

Full compatibility is not an initial acceptance criterion. A migration report
must never silently drop bindings or translate unrecognized PLC write behavior.

## Reference distribution limits

The supplied `AdvancedHMI/UsageAndLicense.txt` describes GPL application source,
restricts graphics to AdvancedHMI, and gives separate redistribution terms for
included DLLs. OpenHMI retains its existing MIT license and independently authors
its implementation. No archive source, controls, graphics or DLLs are copied into
this repository. Any future reuse needs review of the applicable original terms.
