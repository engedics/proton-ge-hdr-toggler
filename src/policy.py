"""HDR catalog policy shared by the Steam and Faugus entry points."""

HELPERS = {'d3ddriverquery.exe', 'd3ddriverquery64.exe', 'iscriptevaluator.exe', 'wineboot.exe',
           'wineserver', 'winedevice.exe', 'steamservice.exe'}


def wants_hdr(appid, catalog, environment):
    override = environment.get('AUTOHDR')
    if override in ('0', '1'):
        return override == '1'
    entry = catalog['games'].get(appid)
    # Mod-only games require a deliberate per-game opt-in after installing a fix.
    return entry is not None and entry['hdr'] in ('true', 'limited', 'always on')
