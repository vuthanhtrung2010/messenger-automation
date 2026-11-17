{
  pkgs,
  lib,
  config,
  inputs,
  ...
}:

let
  libraries = with pkgs; [
    stdenv.cc.cc.lib
    gtk3
    gdk-pixbuf
    glib
    pango
    cairo
    harfbuzz
    fontconfig
    freetype
    dbus
    nss
    nspr
    alsa-lib
    at-spi2-core
    libdrm
    xorg.libX11
    xorg.libXcomposite
    xorg.libXcursor
    xorg.libXdamage
    xorg.libXext
    xorg.libXfixes
    xorg.libXi
    xorg.libXrandr
    xorg.libXrender
    xorg.libXtst
    xorg.libxcb
    xorg.libxshmfence
    libxkbcommon
    libGL
    mesa
    ffmpeg
    udev
  ];
in
{
  packages = [
    pkgs.git
    pkgs.uv
    pkgs.cacert
  ] ++ libraries;

  dotenv.enable = true;

  env.LD_LIBRARY_PATH = "${lib.makeLibraryPath libraries}";
  env.SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";

  enterShell = ''
    export LD_LIBRARY_PATH="${lib.makeLibraryPath libraries}:$LD_LIBRARY_PATH"
    export SSL_CERT_FILE="${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
    export PATH="$PWD/.venv/bin:$PATH"
  '';
}
