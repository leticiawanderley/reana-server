# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
"""REANA-Server utils."""

import base64
import csv
import io
import json
import secrets
from uuid import UUID

import fs
import requests
import yaml
from flask import current_app as app
from reana_commons.k8s.secrets import REANAUserSecretsStore
from reana_db.database import Session
from reana_db.models import User
from sqlalchemy.exc import IntegrityError, InvalidRequestError

from reana_server.config import ADMIN_USER_ID, REANA_GITLAB_URL


def is_uuid_v4(uuid_or_name):
    """Check if given string is a valid UUIDv4."""
    # Based on https://gist.github.com/ShawnMilo/7777304
    try:
        uuid = UUID(uuid_or_name, version=4)
    except Exception:
        return False

    return uuid.hex == uuid_or_name.replace('-', '')


def create_user_workspace(user_workspace_path):
    """Create user workspace directory."""
    reana_fs = fs.open_fs(app.config['SHARED_VOLUME_PATH'])
    if not reana_fs.exists(user_workspace_path):
        reana_fs.makedirs(user_workspace_path)


def get_user_from_token(access_token):
    """Validate that the token provided is valid."""
    user = Session.query(User).filter_by(access_token=access_token).\
        one_or_none()
    if not user:
        raise ValueError('Token not valid.')
    return user


def _get_users(_id, email, user_access_token, admin_access_token):
    """Return all users matching search criteria."""
    admin = Session.query(User).filter_by(id_=ADMIN_USER_ID).one_or_none()
    if admin_access_token != admin.access_token:
        raise ValueError('Admin access token invalid.')
    search_criteria = dict()
    if _id:
        search_criteria['id_'] = _id
    if email:
        search_criteria['email'] = email
    if user_access_token:
        search_criteria['access_token'] = user_access_token
    users = Session.query(User).filter_by(**search_criteria).all()
    return users


def _create_user(email, user_access_token, admin_access_token):
    """Create user with provided credentials."""
    try:
        admin = Session.query(User).filter_by(id_=ADMIN_USER_ID).one_or_none()
        if admin_access_token != admin.access_token:
            raise ValueError('Admin access token invalid.')
        if not user_access_token:
            user_access_token = secrets.token_urlsafe(16)
        user_parameters = dict(access_token=user_access_token)
        user_parameters['email'] = email
        user = User(**user_parameters)
        Session.add(user)
        Session.commit()
    except (InvalidRequestError, IntegrityError) as e:
        Session.rollback()
        raise ValueError('Could not create user, '
                         'possible constraint violation')
    return user


def _export_users(admin_access_token):
    """Export all users in database as csv.

    :param admin_access_token: Admin access token.
    :type admin_access_token: str
    """
    admin = User.query.filter_by(id_=ADMIN_USER_ID).one_or_none()
    if admin_access_token != admin.access_token:
        raise ValueError('Admin access token invalid.')
    csv_file_obj = io.StringIO()
    csv_writer = csv.writer(csv_file_obj, dialect='unix')
    for user in User.query.all():
        csv_writer.writerow([user.id_, user.email, user.access_token])
    return csv_file_obj


def _import_users(admin_access_token, users_csv_file):
    """Import list of users to database.

    :param admin_access_token: Admin access token.
    :type admin_access_token: str
    :param users_csv_file: CSV file object containing a list of users.
    :type users_csv_file: _io.TextIOWrapper
    """
    admin = User.query.filter_by(id_=ADMIN_USER_ID).one_or_none()
    if admin_access_token != admin.access_token:
        raise ValueError('Admin access token invalid.')
    csv_reader = csv.reader(users_csv_file)
    for row in csv_reader:
        user = User(id_=row[0], email=row[1], access_token=row[2])
        Session.add(user)
    Session.commit()
    Session.remove()


def _create_and_associate_reana_user(sender, token=None,
                                     response=None, account_info=None):
    try:
        user_email = account_info['user']['email']
        search_criteria = dict()
        search_criteria['email'] = user_email
        users = Session.query(User).filter_by(**search_criteria).all()
        if users:
            user = users[0]
        else:
            user_access_token = secrets.token_urlsafe(16)
            user_parameters = dict(access_token=user_access_token)
            user_parameters['email'] = user_email
            user = User(**user_parameters)
            Session.add(user)
            Session.commit()
    except (InvalidRequestError, IntegrityError):
        Session.rollback()
        raise ValueError('Could not create user, '
                         'possible constraint violation')
    except Exception:
        raise ValueError('Could not create user')
    return user


def _get_user_from_invenio_user(id):
    user = Session.query(User).filter_by(email=id).one_or_none()
    if not user:
        raise ValueError('No users registered with this id')
    return user


def _get_reana_yaml_from_gitlab(webhook_data, user_id):
    gitlab_api = REANA_GITLAB_URL + "/api/v4/projects/{0}" + \
                 "/repository/files/{1}/raw?ref={2}&access_token={3}"
    reana_yaml = 'reana.yaml'
    if webhook_data['object_kind'] == 'push':
        branch = webhook_data['project']['default_branch']
        commit_sha = webhook_data['checkout_sha']
    elif webhook_data['object_kind'] == 'merge_request':
        branch = webhook_data['object_attributes']['source_branch']
        commit_sha = webhook_data['object_attributes']['last_commit']['id']
    secrets_store = REANAUserSecretsStore(str(user_id))
    gitlab_token = secrets_store.get_secret_value('gitlab_access_token')
    project_id = webhook_data['project']['id']
    yaml_file = requests.get(gitlab_api.format(project_id, reana_yaml,
                                               branch, gitlab_token))
    return yaml.load(yaml_file.content), \
        webhook_data['project']['path_with_namespace'], branch, \
        commit_sha


def _format_gitlab_secrets(gitlab_response):
    access_token = json.loads(gitlab_response)['access_token']
    user = json.loads(
                requests.get(REANA_GITLAB_URL + '/api/v4/user?access_token={0}'
                             .format(access_token)).content)
    return {
        "gitlab_access_token": {
            "value": base64.b64encode(
                        access_token.encode('utf-8')).decode('utf-8'),
            "type": "env"
        },
        "gitlab_user": {
            "value": base64.b64encode(
                        user['username'].encode('utf-8')).decode('utf-8'),
            "type": "env"
        }
    }
