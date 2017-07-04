# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017 CERN.
#
# REANA is free software; you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# REANA is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with REANA; if not, see <http://www.gnu.org/licenses>.
#
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization or
# submit itself to any jurisdiction.

"""Reana-Server Ping-functionality Flask-Blueprint."""

import json

from flask import current_app as app
from flask import Blueprint, jsonify, request

from ..api_client import create_openapi_client

blueprint = Blueprint('analyses', __name__)
rwc_api_client = create_openapi_client('reana-workflow-controller')


@blueprint.route('/analyses', methods=['GET'])
def get_analyses():  # noqa
    r"""Get all analyses.

    ---
    get:
      summary: Returns list of all analyses.
      description: >-
        This resource return all analyses in JSON format.
      produces:
       - application/json
      responses:
        200:
          description: >-
            Request succeeded. The response contains the list of all analyses.
          schema:
            type: array
            items:
              type: object
              properties:
                id:
                  type: string
                organization:
                  type: string
                status:
                  type: string
                user:
                  type: string
          examples:
            application/json:
              [
                {
                  "id": "256b25f4-4cfb-4684-b7a8-73872ef455a1",
                  "organization": "default_org",
                  "status": "running",
                  "user": "00000000-0000-0000-0000-000000000000"
                },
                {
                  "id": "3c9b117c-d40a-49e3-a6de-5f89fcada5a3",
                  "organization": "default_org",
                  "status": "finished",
                  "user": "00000000-0000-0000-0000-000000000000"
                },
                {
                  "id": "72e3ee4f-9cd3-4dc7-906c-24511d9f5ee3",
                  "organization": "default_org",
                  "status": "waiting",
                  "user": "00000000-0000-0000-0000-000000000000"
                },
                {
                  "id": "c4c0a1a6-beef-46c7-be04-bf4b3beca5a1",
                  "organization": "default_org",
                  "status": "waiting",
                  "user": "00000000-0000-0000-0000-000000000000"
                }
              ]
        500:
          description: >-
            Request failed. Internal controller error.
          examples:
            application/json:
              {
                "message": "Either organization or user doesn't exist."
              }
    """
    try:
        res = rwc_api_client.api.get_workflows(
            organization='default',
            user='00000000-0000-0000-0000-000000000000').result()
        return jsonify(res), 200
    except Exception as e:
        return jsonify({"message": str(e)}), 500


@blueprint.route('/analyses', methods=['POST'])
def create_analysis():  # noqa
    r"""Create a analysis.

    ---
    post:
      summary: Creates a new yadage workflow.
      description: >-
        This resource is expecting JSON data with all the necessary
        informations to instantiate a yadage workflow.
      operationId: create_yadage_workflow
      consumes:
        - multipart/form-data
      produces:
        - application/json
      parameters:
        - name: organization
          in: query
          description: Required. Organization which the worklow belongs to.
          required: true
          type: string
        - name: user
          in: query
          description: Required. UUID of workflow owner.
          required: true
          type: string
        - name: workflow_engine
          in: query
          description: Required. Name of the workflow engine to be used.
          required: true
          type: string
        - name: analysis_payload
          in: formData
          description: Specification with necessary data to instantiate an
            analysis for the given workflow engine.
          required: true
          type: file
      responses:
        200:
          description: >-
            Request succeeded. The workflow has been instantiated.
          schema:
            type: object
            properties:
              message:
                type: string
              workflow_id:
                type: string
          examples:
            application/json:
              {
                "message": "Analysis successfully launched",
                "workflow_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac"
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed
    """
    try:
        workflow_engine = request.args.get('workflow_engine')
        if workflow_engine not in app.config['AVAILABLE_WORKFLOW_ENGINES']:
            raise Exception('Unknown workflow engine')
        binary_file = request.files['analysis_payload'].stream.read()
        analysis_payload = json.loads(binary_file.decode('UTF-8'))
        if workflow_engine == 'yadage':
            res = rwc_api_client.api.create_yadage_workflow(
                yadage_payload={
                    'toplevel': analysis_payload['toplevel'],
                    'workflow': analysis_payload['workflow'],
                    'nparallel': analysis_payload['nparallel'],
                    'preset_pars': analysis_payload['preset_pars']},
                organization=request.args.get('organization'),
                user=request.args.get('user')).result()
        return jsonify(res), 200
    except KeyError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        return jsonify({"message": str(e)}), 500
