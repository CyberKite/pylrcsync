# PyLRCSync

An LRC timestamp editor for video terminals

## Usage

### Getting Started

* Prepare your text lyrics to match up with the song
* `./main.py path/to/lyrics.lrc path/to/song.flac`

### Controls

| Bind      | Action                                |
|-----------|---------------------------------------|
| `j` / `k` | move between lines                    |
| `Space`   | timestamp current line and advance    |
| `←` / `→` | seek song by 1 second                 |
| `p`       | toggle playback                       |
| `[` / `]` | decrease/increase playback speed      |
| `?`       | show help                             |
|           |                                       |
| `h` / `l` | adjust timestamp by -/+ 50 ms         |
| `H` / `L` | adjust timestamp by -/+ 250 ms        |
| `Enter`   | seek to current line and play         |
|           |                                       |
| `e`       | edit buffer in text editor            |
| `u`       | undo                                  |
| `w`       | save                                  |
| `q`       | quit if unmodified                    |
|           |                                       |
| `{` / `}` | halve/double playback speed           |
| `=`       | reset playback speed                  |
|           |                                       |
| `t`       | timestamp current line                |
| `s`       | seek to current line, don't play      |
| `P`       | pause                                 |
| `x`       | save and quit                         |
| `Q`       | quit without saving                   |

## Requirements

- Python >= 3.12
    - `type` keyword
    - ...isn't Python 2 code...?
- mpv
    - on `PATH`
    - responsible for timekeeping/audio playback
- ...a cursor-addressable terminal
    - color support is optional :3

## Contributing

Vibe-coded PRs welcome so long as they're human-reviewed ---
If you can't write Python, consider submitting a feature request instead.

Do note that I am extremely pedantic and will probably
find something to complain about, no matter how clean the diff.
Fork the project if you don't like it.
I will absolutely cherry pick your commits, though, in that case.

## License

[MIT](LICENSE.txt)
