"""Resolve a named post-FX input without falling back to an OS microphone."""
from .audio import reject_bridge_capture


def choose_named_input(devices, apis, name: str, api: str, channels: int) -> int:
    candidates = [i for i, d in enumerate(devices) if d['name'].strip().casefold() == name.strip().casefold()
                  and apis[d['hostapi']]['name'].casefold() == api.casefold()
                  and d['max_input_channels'] >= channels]
    if len(candidates) != 1:
        raise ValueError('Post-FX input name/API is missing or ambiguous; enumerate devices, never choose default microphone')
    index = candidates[0]
    reject_bridge_capture(devices[index]['name'])
    if float(devices[index]['default_samplerate']) != 48000:
        raise ValueError('Set this source device to48k in Audio MIDI Setup first; no automatic rate change')
    return index
