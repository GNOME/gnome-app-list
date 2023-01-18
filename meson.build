# Copyright 2023 Endless OS Foundation, LLC
# SPDX-License-Identifier: LGPL-2.1-or-later

project('gnome-app-list',
  license: 'LGPL-2.1-or-later',
)

swcatalogdir = get_option('datadir') / 'swcatalog' / 'xml'

gnome_app_list_curated = install_data('org.gnome.Apps.Curated.xml',
  install_dir: swcatalogdir,
)
gnome_app_list_featured = install_data('org.gnome.Apps.Featured.xml',
  install_dir: swcatalogdir,
)