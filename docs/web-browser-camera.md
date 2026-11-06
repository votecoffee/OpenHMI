# Web Browser / Camera View

Add **Web Browser / Camera View** to a grid or freeform screen, then configure
its approved endpoint in the property editor. The designer shows a placeholder.
The embedded page opens on the live screen.

1. Set **Scheme**, **Approved hosts**, optional **Port** and **Approved path**.
   Enter exact DNS names or IPv4 addresses separated by commas. Leave the port
   blank to use 443 for HTTPS or 80 for HTTP. Use a plain absolute path such
   as /view. The control accepts neither URL credentials nor query strings,
   fragments, wildcards or encoded paths.
2. Leave **Address from tag** unbound to use the first approved host. To select
   a camera from a PLC, bind a STRING containing an approved host or the full
   URL that matches the configured scheme, host, port and path. For example,
   with HTTPS, approved hosts camera-a.invalid and camera-b.invalid, and path
   /view, the tag can contain camera-b.invalid or
   https://camera-b.invalid/view. The PLC supplies a choice within the approved
   endpoints.
3. Optionally bind **Refresh from tag** to a BOOL or integer. A BOOL reloads on
   a sampled rising edge and an integer reloads on a sampled change. The first
   good value after opening the view, changing address or losing refresh quality
   establishes the baseline. Keep a BOOL pulse long enough for the screen to
   sample it, or use an integer sequence. Manual and PLC-triggered refreshes
   share a one-second minimum interval and coalesce while a reload is pending.
   If the refresh tag loses quality while a PLC-triggered reload is queued,
   the control cancels it. Manual refresh remains available for an approved
   address.

An invalid address or unavailable address sample removes the embedded page and
its navigation actions. Address and refresh bindings use ordinary read-only
screen demand. The control never writes PLC values.

## Embedding and station checks

The embedded page runs in a sandbox with an opaque origin and an isolated
browser credential context. The frame restricts navigation to the selected
origin. The approved path governs the URL requested by OpenHMI. A trusted
endpoint can redirect within that origin or load its own resources. Use a
camera viewing endpoint whose content and redirects you control. OpenHMI
blocks the HMI hostname as a camera destination.

The status remains **Camera health unverified** after a browser load event.
Frame restrictions, local-network permissions, TLS issues or an unreachable
camera may produce a blank or blocked view. **Open camera in new tab** is a
deliberate operator action and uses the station's regular browser session
without passing an opener or referrer. HTTPS stations offer this fallback
for HTTP cameras, and browsers without credential isolation offer it for all
approved endpoints.

Verify the approved URL and viewing mode on the actual Windows operator
station with its intended browser, network permissions, camera firmware and
display scale. Exercise address quality changes, both refresh methods when in
scope, and the fallback. OpenHMI currently supports browser-viewable pages.
RTSP conversion, camera administration and authentication relay are separate
work. [Chromium iframe credential isolation](https://developer.chrome.com/blog/iframe-credentialless)
· [CSP redirect path rules](https://www.w3.org/TR/CSP3/#paths-and-redirects)
