"""Cornice services."""
from datetime import datetime
import json
from os import makedirs
from os.path import join, abspath, dirname, exists, isdir, normpath

from cornice import Service
from pyramid.exceptions import ConfigurationError, Forbidden, NotFound
from pyramid.httpexceptions import HTTPNotImplemented

from diecutter import __version__ as VERSION
from diecutter.engines.jinja import Jinja2Engine
from diecutter import resources
from diecutter.contextextractors import extract_context
from diecutter.exceptions import TemplateError
from diecutter.validators import token_validator


template_service = Service(name='template_service', path='/',
                           description="The template API")

conf_template = Service(name='template', path='/{template_path:.+}',
                        description="Return the template render or raw")


def get_template_dir(request):
    """Return validated template directory configuration for request."""
    try:
        template_dir = request.registry.settings['diecutter.template_dir']
    except KeyError:
        error_msg = 'Missing mandatory "diecutter.template_dir" setting.'
        raise ConfigurationError(error_msg)
    if not template_dir:
        error_msg = 'Mandatory "diecutter.template_dir" setting is empty.'
        raise ConfigurationError(error_msg)
    return template_dir


def get_resource_path(request):
    """Return validated (absolute) resource path from request.

    Checks that resource path is inside request's template_dir.

    """
    template_dir = get_template_dir(request)
    filename = request.matchdict['template_path']
    file_path = normpath(abspath(join(template_dir, filename)))
    if not file_path.startswith(template_dir):
        NotFound('Ressource not found.')
    if filename.endswith('/'):  # Preserve trailing '/'
        file_path += '/'
    return file_path


def get_resource(request):
    """Return the resource matching request.

    Return value is a :py:class:`FileResource` or :py:class`DirResource`.

    """
    path = get_resource_path(request)
    if isdir(path):
        resource = resources.DirResource(path=path, engine=Jinja2Engine())
    else:
        resource = resources.FileResource(path=path, engine=Jinja2Engine())
    return resource


def to_boolean(value):
    _BOOL_STATES = {'1': True, 'yes': True, 'true': True, 'on': True,
                    '0': False, 'no': False, 'false': False, 'off': False}

    value = str(value).lower().strip()
    if value not in _BOOL_STATES:
        raise ValueError(value)
    return _BOOL_STATES[value]


def is_readonly(request):
    """Return "readonly" flag status (boolean) for request.

    As an example, PUT operations should be forbidden if readonly flag is On.

    """
    return to_boolean(request.registry.settings.get('diecutter.readonly',
                                                    False))


@template_service.get()
def get_hello(request):
    """Returns Hello in JSON."""
    return {'diecutter': 'Hello', 'version': VERSION}


@conf_template.put(validators=(token_validator,))
def put_template(request):
    if is_readonly(request):
        raise Forbidden('This diecutter server is readonly.')
    filename = request.matchdict['template_path']
    input_file = request.POST['file'].file

    file_path = get_resource_path(request)

    if not exists(dirname(file_path)):
        makedirs(dirname(file_path))

    with open(file_path, 'w') as output_file:
        # Finally write the data to the output file
        input_file.seek(0)
        for line in input_file.readlines():
            output_file.write(line)
    request.response.status_int = 201
    request.response.headers['location'] = str('/%s' % filename)
    return {'diecutter': 'Ok'}


@conf_template.get()
def get_conf_template(request):
    resource = get_resource(request)
    if not resource.exists:
        return NotFound('Template not found')
    request.response.content_type = 'text/plain'
    request.response.write(resource.read())
    return request.response


@conf_template.post()
def post_conf_template(request):
    resource = get_resource(request)
    try:
        context = extract_context(request)
    except NotImplementedError as e:
        raise HTTPNotImplemented(e.message)
    context['diecutter'] = {
        'api_url': '%s://%s' % (request.environ['wsgi.url_scheme'],
                                request.environ['HTTP_HOST']),
        'version': VERSION,
        'now': datetime.now()}
    if not resource.exists:
        return NotFound('Template not found')
    request.response.content_type = resource.content_type
    try:
        request.response.write(resource.render(context))
    except TemplateError as e:
        request.response.status_int = 500
        request.response.write(json.dumps(str(e)))
    return request.response
