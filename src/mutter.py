"""Mutter DisplayConfig client. Requires Python GObject introspection (gi)."""
from __future__ import annotations
from gi.repository import Gio, GLib

BUS = 'org.gnome.Mutter.DisplayConfig'
PATH = '/org/gnome/Mutter/DisplayConfig'
IFACE = BUS
# Mutter's documented enum: default=0, bt2100=1, sdr-native=2.
HDR = 1


def unbox(value):
    return value.unpack() if isinstance(value, GLib.Variant) else value


def get_state():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    reply = bus.call_sync(BUS, PATH, IFACE, 'GetCurrentState', None, None,
                          Gio.DBusCallFlags.NONE, 10000, None)
    return reply.unpack()


def layout_from_state(state, *, target=None, color=None):
    """Rebuild active logical monitors, preserving mode IDs, VRR, scale and placement.

    Only color-mode is intentionally changed. Other monitor properties are not
    blindly copied into ApplyMonitorsConfig (they may be read-only).
    """
    _, monitors, logicals, props = state
    by_connector = {m[0][0]: m for m in monitors}
    output = []
    for lm in logicals:
        x, y, scale, transform, primary, physicals, _ = lm
        configured = []
        for physical in physicals:
            connector = physical[0]
            info = by_connector[connector]
            current = next((mode for mode in info[1] if unbox(mode[6].get('is-current', False))), None)
            if current is None:
                raise RuntimeError(f'No active mode for {connector}')
            current_color = unbox(info[2].get('color-mode', 0))
            requested = color if connector == target else current_color
            properties = {'color-mode': GLib.Variant('u', int(requested))}
            if 'is-underscanning' in info[2]:
                properties['underscanning'] = GLib.Variant('b', bool(unbox(info[2]['is-underscanning'])))
            if 'rgb-range' in info[2]:
                properties['rgb-range'] = GLib.Variant('u', int(unbox(info[2]['rgb-range'])))
            configured.append((connector, current[0], properties))
        output.append((int(x), int(y), float(scale), int(transform), bool(primary), configured))
    return output


def primary_connector(state):
    for lm in state[2]:
        if lm[4] and lm[5]:
            return lm[5][0][0]
    raise RuntimeError('No active primary monitor')


def color_for(state, connector):
    monitor = next(m for m in state[1] if m[0][0] == connector)
    return int(unbox(monitor[2].get('color-mode', 0)))


def apply(state, target=None, color=None):
    # GVariant type of the monitor configuration: a(iiduba(ssa{sv})).
    config = layout_from_state(state, target=target, color=color)
    serial = int(state[0])
    properties = {}
    if unbox(state[3].get('supports-changing-layout-mode', False)):
        properties['layout-mode'] = GLib.Variant('u', int(unbox(state[3].get('layout-mode', 1))))
    args = GLib.Variant('(uua(iiduba(ssa{sv}))a{sv})',
                        (serial, 1, config, properties))
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync(BUS, PATH, IFACE, 'ApplyMonitorsConfig', args, None,
                  Gio.DBusCallFlags.NONE, 15000, None)


def active_connectors(state):
    return {physical[0] for logical in state[2] for physical in logical[5]}


def snapshot(connector=None):
    state = get_state()
    connector = connector or primary_connector(state)
    if connector not in active_connectors(state):
        raise RuntimeError(f'Monitor {connector} is not active')
    monitor = next(m for m in state[1] if m[0][0] == connector)
    if HDR not in unbox(monitor[2].get('supported-color-modes', [])):
        raise RuntimeError(f'Monitor {connector} does not advertise BT.2100 support')
    previous = color_for(state, connector)
    return {'connector': connector, 'monitor_id': list(monitor[0]),
            'original_color': previous, 'changed': previous != HDR}


def transition(saved, requested, *, only_if_hdr=False):
    connector = saved['connector']
    for attempt in range(3):
        state = get_state()
        if connector not in active_connectors(state):
            raise RuntimeError(f'Monitor {connector} is not active; keeping recovery state')
        monitor = next(m for m in state[1] if m[0][0] == connector)
        if saved.get('monitor_id') and list(monitor[0]) != saved['monitor_id']:
            raise RuntimeError(f'A different monitor now uses {connector}; keeping recovery state')
        current = color_for(state, connector)
        if current == requested or (only_if_hdr and current != HDR):
            return
        try:
            apply(state, connector, requested)
        except GLib.Error as exc:
            if attempt < 2 and 'stale' in str(exc).lower():
                continue
            raise
        if color_for(get_state(), connector) != requested:
            raise RuntimeError(f'Mutter did not report requested color mode {requested} for {connector}')
        return


def enable(saved):
    transition(saved, HDR)


def restore(snapshot):
    if not snapshot['changed']:
        return
    transition(snapshot, int(snapshot['original_color']), only_if_hdr=True)


def status():
    state = get_state()
    active = active_connectors(state)
    primary = primary_connector(state) if state[2] else None
    monitors = []
    for physical, modes, properties in state[1]:
        current = next((mode for mode in modes if unbox(mode[6].get('is-current', False))), None)
        logical = next((lm for lm in state[2] if any(p[0] == physical[0] for p in lm[5])), None)
        monitors.append({'connector': physical[0], 'active': physical[0] in active,
                         'primary': physical[0] == primary,
                         'color_mode': int(unbox(properties.get('color-mode', 0))),
                         'supported_color_modes': unbox(properties.get('supported-color-modes', [])),
                         'mode_id': current[0] if current else None,
                         'refresh_hz': current[3] if current else None,
                         'scale': logical[2] if logical else None})
    return {'monitors': monitors}
