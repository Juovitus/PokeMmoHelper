# PokeMmoHelper

A small always-on-top overlay for PokeMMO with a daily gym checklist, step-by-step Elite Four guides, and a berry planter timer.

It is a separate program. It never reads the game's memory, injects anything, or sends input. It only asks Windows where the PokeMMO window is so it can sit next to it. You click everything yourself.

## Features

- **Gym Tracker**: daily checklist for every region's gyms, with the team and moves to use for each. Resets daily.
- **Elite Four guides**: choose your team and region, pick the champion and their lead, then follow the steps. Buttons let you say what the opponent did, and the guide branches from there. It shows sprites, the opponent's possible teams, and warnings for risky steps.
- **Berry Planter**: track planted berries, growth timers and watering, with a progress bar in the title bar.
- **Overlay**: pins to the PokeMMO window or can be moved freely, collapses to a title bar, and stays on top.
- **Auto-update**: tells you when a new release is out and updates itself with one click.

## Download

Get `PokeMmoHelper.exe` from the [latest release](https://github.com/Juovitus/PokeMmoHelper/releases/latest) and run it. No install needed. Your progress and settings are saved next to the exe.

## Elite Four teams

The guides cover six teams: Dingxianyou, Shadow Scale, Reversed Fate, Starlight, Ghost Dance and Sacred Inferno.

**Dingxianyou** has been re-translated and cleaned up from the original Chinese guide. The other teams still use an older machine translation and may have translation errors. The app shows a warning for those teams.

## Building from source

Requires Python 3 on Windows.

```
build_exe.bat
```

This builds a single `PokeMmoHelper.exe` (via PyInstaller) with the guide data (`e4/`) and sprites (`sprites/`) packed inside. You can also run it directly with `python PokeMmoHelper.py`.

## Credits

The Elite Four guides come from PokeKING (pokeking.icu). Opponent team data is cross-checked against the [PokeMMO wiki](https://pokemmo.shoutwiki.com/wiki/Elite_Four). Sprites are from [PokeAPI](https://pokeapi.co/).
