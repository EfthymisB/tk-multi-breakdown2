# Copyright (c) 2021 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os

import sgtk

import alias_api

HookBaseClass = sgtk.get_hook_baseclass()


class BreakdownSceneOperations(HookBaseClass):
    """
    Breakdown operations for Alias.

    This implementation handles detection of Alias references.
    """

    def scan_scene(self):
        """
        The scan scene method is executed once at startup and its purpose is
        to analyze the current scene and return a list of references that are
        to be potentially operated on.

        The return data structure is a list of dictionaries. Each scene reference
        that is returned should be represented by a dictionary with three keys:

        - "node_name": The name of the 'node' that is to be operated on. Most DCCs have
          a concept of a node, path or some other way to address a particular
          object in the scene.
        - "node_type": The object type that this is. This is later passed to the
          update method so that it knows how to handle the object.
        - "path": Path on disk to the referenced object.
        - "extra_data": Optional key to pass some extra data to the update method
          in case we'd like to access them when updating the nodes.

        Toolkit will scan the list of items, see if any of the objects matches
        a published file and try to determine if there is a more recent version
        available. Any such versions are then displayed in the UI as out of date.
        """

        refs = []

        # only deal with references matching a template
        for r in alias_api.get_references():

            reference_template = self._get_reference_template_from_path(r.source_path)
            if not reference_template:
                reference_template = self._get_reference_template_from_path(r.path)

            # here, we've imported a file as reference and we need to use the source path to get the next
            # available version
            if reference_template and reference_template.validate(r.path):
                refs.append(
                    {
                        "node_name": r.name,
                        "node_type": "reference",
                        "path": r.source_path.replace("/", os.path.sep),
                    }
                )
            else:
                refs.append(
                    {
                        "node_name": r.name,
                        "node_type": "reference",
                        "path": r.path.replace("/", os.path.sep),
                    }
                )

        return refs

    def update(self, item):
        """
        Perform replacements given a number of scene items passed from the app.

        Once a selection has been performed in the main UI and the user clicks
        the update button, this method is called.

        :param item: Dictionary on the same form as was generated by the scan_scene hook above.
                     The path key now holds the path that the node should be updated *to* rather than the current path.
        """

        node_type = item["node_type"]
        path = item["path"]
        extra_data = item["extra_data"]

        if node_type == "reference":
            self.update_reference(path, extra_data)

    def update_reference(self, path, extra_data):
        """"""

        old_path = extra_data["old_path"]

        _, ext = os.path.splitext(path)

        # if the new path is not a path to a wref file, we need to handle the conversion
        if ext != ".wref":

            # get the Alias Translations framework to translate the file to wref before importing it
            framework = self.load_framework("tk-framework-aliastranslations_v0.x.x")
            if not framework:
                self.logger.error(
                    "Couldn't load tk-framework-aliastranslations. Skipping reference update for file {}.".format(
                        path
                    )
                )
                return

            tk_framework_aliastranslations = framework.import_module(
                "tk_framework_aliastranslations"
            )

            source_template = self.sgtk.template_from_path(path)
            reference_template = self._get_reference_template_from_path(path)

            if source_template and reference_template:

                template_fields = source_template.get_fields(path)
                template_fields["alias.extension"] = ext[1:]
                reference_path = reference_template.apply_fields(template_fields)

                # do the same for the old path in order to get the associated reference path
                template_fields = source_template.get_fields(old_path)
                template_fields["alias.extension"] = ext[1:]
                old_path = reference_template.apply_fields(template_fields)

                if os.path.exists(reference_path):
                    self.logger.debug("File already converted!")
                    path = reference_path

                else:
                    self.logger.debug("Translating file to wref...")
                    translator = tk_framework_aliastranslations.Translator(
                        path, reference_path
                    )
                    translator.execute()
                    path = reference_path

            else:
                self.logger.error(
                    "Couldn't convert file to wref, missing templates. Skipping file {}...".format(
                        path
                    )
                )
                return

        if not old_path or not os.path.exists(old_path):
            self.logger.info(
                "Couldn't find old reference path. Skipping file {}".format(path)
            )
            return

        # get the reference by its uuid if possible, otherwise use its name to find the right instance
        alias_api.update_reference(old_path, path)

    def _get_reference_template_from_path(self, file_path):
        """
        Get the reference template from the reference file path

        :param file_path: Path to the reference file
        :returns:  Th reference template if we could find it, None otherwise
        """

        # we need to get the context from the path in order to be able to look for the right configuration section and
        # find the reference template linked to the right entity type
        ctx = self.sgtk.context_from_path(file_path)
        if not ctx:
            return

        env = sgtk.platform.engine.get_environment_from_context(self.parent.sgtk, ctx)
        if not env:
            return

        engine_settings = env.get_engine_settings(self.parent.engine.name)
        if not engine_settings:
            return

        reference_template_name = engine_settings.get("reference_template")
        if not reference_template_name:
            return

        return self.parent.engine.get_template_by_name(reference_template_name)
