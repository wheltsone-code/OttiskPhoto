# Локальный модуль векторного импорта / Local vector import module

Распакуйте папку `import-module` рядом с `OttiskPhoto.exe`. Внутри должны находиться `inkscape/bin/inkscape.com`, `inkscape/bin/inkscape.exe` и `ghostscript/bin/gswin64c.exe`. Сохраняйте всю структуру папок. Python, Illustrator, CorelDRAW, Office и инструменты сборки устанавливать не требуется. Файлы обрабатываются локально.

Extract the `import-module` folder beside `OttiskPhoto.exe`, preserving the complete directory structure. No separately installed Python, Illustrator, CorelDRAW, Office or development tools are required. Conversion runs locally.

Inkscape 1.4.2 (f4327f4) imports SVG and the CDR versions understood by its bundled libcdr. Ghostscript 10.08.0 converts EPS and recognized Illustrator PostScript. PDF-compatible AI is read directly. Unknown AI contents and CDR signatures are rejected; parser acceptance is still required after signature recognition. CDR import does not certify all versions, effects or pages. Check the imported document, especially fonts and page count.

The module is separate because the unchanged portable runtime occupies roughly 641 MiB before compression; placing it inside the one-file application would increase every app update and extraction time. Both programs run as independent local processes. No Word import code, LibreOffice or Word-specific dependency is used. Inkscape includes its upstream extension runtime; it is not a separately required developer installation.

## Upstream distributions and source

* Inkscape binaries: https://inkscape.org/release/inkscape-1.4.2/windows/64-bit/compressed-7z/
* Inkscape source and build instructions: https://inkscape.org/release/inkscape-1.4.2/source/archive/xz/
* Inkscape license: GPL 2.0 or later; retain licenses for its bundled libraries.
* Ghostscript binaries and corresponding source: https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/tag/gs10080
* Ghostscript license: GNU AGPL 3.0, included in `ghostscript/doc/COPYING`; commercial licensing is available separately from Artifex.

The local delivery includes the corresponding main-program source archives in the separate source package. Keep upstream notices and provide applicable corresponding source/build material when redistributing these third-party programs. This module has not been published or installed system-wide by the build workflow. The complete license/source inventory for the Windows dependency bundle must be reviewed before public distribution; the application build is a local candidate.

## Cache and limitations

The application stores disposable intermediate PDFs and expensive screen rasters under `%LOCALAPPDATA%/OttiskPhoto/Cache/v1`. Source files remain unchanged. Inkscape multipage SVG output is recombined as vector PDF pages; declared SVG page sizes are restored after converter rounding. EPS/PS has the transparency and page/artboard limitations of PostScript. Embedded vector text is preserved when the converter can represent it; effects may be rasterized by the converter. Colour adjustments require raster output at the selected output density.

SVG linked images/fonts must be embedded before import. External resources, DTDs and scripts are rejected. Missing SVG font families are reported where Windows font inventory permits detection. Converters may silently substitute fonts in other formats; a warning is shown. PDF/AI files with embedded fonts retain those fonts through the existing PDF pipeline.

Tested locally with PATH excluding developer tools, but a separate clean Windows machine/VM and a physical printer remain release checks.
