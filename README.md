# GNOME app list

This repository is a place to maintain a curated list of apps to feature or
highlight in GNOME, particularly in
[GNOME Software](https://gitlab.gnome.org/GNOME/gnome-software).

The goals of the repository are to:

1. Decouple app curation from the maintenance and release cycle of gnome-software
2. Provide an official curated list of apps from the GNOME project
3. Coordinate curation efforts between different distributions

There is more context available in the discussion on
[this issue](https://gitlab.gnome.org/GNOME/gnome-software/-/issues/1982#note_1633421).

## Criteria for inclusion

To be eligible for inclusion, apps must:
 - be a member of [GNOME Circle](https://circle.gnome.org/) or one of the core
   GNOME release modulesets; and
 - (if in a moduleset not GNOME Circle) follow all [the requirements of being a
   member of GNOME Circle](https://gitlab.gnome.org/Teams/Releng/AppOrganization/-/blob/main/AppCriteria.md),
 - including [these additional proposed requirements](https://gitlab.gnome.org/Teams/Releng/AppOrganization/-/merge_requests/5).

## Process for adding to the list

1. Determine that the app meets all the criteria above.
2. Decide whether the app is to go in the
   [‘curated’ or ‘featured’ list](https://gitlab.gnome.org/GNOME/gnome-software/-/blob/main/doc/vendor-customisation.md#featured-apps-and-editors-choice)
3. Add a `<component>` for it to the relevant XML file, following existing examples.
4. Open a [merge request](https://gitlab.gnome.org/pwithnall/gnome-app-list/-/merge_requests).

