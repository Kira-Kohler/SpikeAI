# Qt / PySide6 / Shiboken notice

This application uses unmodified PySide6 6.7.3, Shiboken6 6.7.3 and Qt 6.7.3.
Copyright The Qt Company Ltd. and other contributors. The application uses the
open-source LGPL v3 option for the applicable Qt Core/Gui/Widgets components.
License texts LGPL-3.0-only.txt and GPL-3.0-only.txt are included beside this notice.

The Windows build loads Qt, PySide6 and Shiboken as separate dynamic libraries from
`_internal/PySide6` and `_internal/shiboken6`. In the standalone build (`dist/Spike AI`)
they can be replaced with compatible modified versions. The Microsoft Store package is
installed by Windows into a read-only folder; to run Spike AI with modified libraries,
build the standalone version from source. Users may reverse-engineer the application as
necessary to debug modifications to those libraries, and Spike AI imposes no terms that
restrict the rights granted by the LGPL.

The complete source code and build specification of Spike AI are published at
https://github.com/Kira-Kohler/SpikeAI

Upstream corresponding source, exact release:
https://download.qt.io/archive/qt/6.7/6.7.3/submodules/
https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.7.3
Qt base includes third-party notices for bundled codecs/fonts/libraries; their original
licenses remain applicable. The binaries have not been modified by Spike AI.

Licensing guidance:
https://www.qt.io/development/open-source-lgpl-obligations
https://www.qt.io/faq/qt-open-source-licensing
