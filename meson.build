# Copyright 2023 Endless OS Foundation, LLC
# SPDX-License-Identifier: LGPL-2.1-or-later

project('gnome-app-list',
  license: 'LGPL-2.1-or-later',
)

app_lists = files(
  'org.gnome.Apps.Curated.xml',
  'org.gnome.Apps.Featured.xml',
)
swcatalogdir = get_option('datadir') / 'swcatalog' / 'xml'

install_data(app_lists,
  install_dir: swcatalogdir,
)

# Validation. We can’t use `appstreamcli validate` because it doesn’t handle
# merged components properly — see https://github.com/ximion/appstream/issues/455
xmllint = find_program('xmllint', required: false)
if xmllint.found()
  test(
    'xmllint AppStream files',
    xmllint,
    args: ['--nonet', '--noout'] + app_lists,
  )
endif
