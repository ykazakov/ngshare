'''
    Tests for ngshare APIs
'''

import os
import json
import base64
import hashlib
import datetime
import tempfile
import shutil
from urllib.parse import urlencode
import pytest
from tornado.httputil import url_concat

from .ngshare import (
    MyApplication,
    MyHelpers,
    MockAuth,
    RequestHandler,
    MyHelpers,
    MyRequestHandler,
    main,
)

application, db_name, storage_name = None, None, None
user, hc, bu = None, None, None


@pytest.fixture
def app():
    'Create Tornado application for testing'
    global application, db_name, storage_name
    # Create temporary location for db and storage
    if db_name is None:
        db_name = tempfile.mktemp('.db')
        storage_name = tempfile.mktemp('-ngshare-test-dir')
    # set necessary environment variables
    os.environ["JUPYTERHUB_API_URL"] = "http://hub.api"
    os.environ["JUPYTERHUB_API_TOKEN"] = "token"
    os.environ["JUPYTERHUB_CLIENT_ID"] = "ngshare-client"
    os.environ["JUPYTERHUB_SERVICE_PREFIX"] = "service/prefix/"
    application = MyApplication(
        '/api/',
        'sqlite:///' + db_name,
        storage_name,
        admin=['root'],
        debug=True,
    )
    # Monkey patch auth methods
    MyRequestHandler.get_current_token = MockAuth.get_current_token
    MyRequestHandler.user_for_token = MockAuth.user_for_token
    return application


async def server_communication(url, data=None, params=None, method='GET'):
    'Request a page'
    global hc, bu, user
    if user is not None:
        if method != 'POST':
            params = params if params is not None else {}
            params['user'] = user
        else:
            data = data if data is not None else {}
            data['user'] = user
    actual_url = bu + url_concat(url, params)
    if method != 'POST':
        body = None
    else:
        body = urlencode(data)
    response = await hc.fetch(
        actual_url, method=method, body=body, raise_error=False
    )
    return response


async def assert_fail(url, data=None, params=None, method='GET', msg=None):
    'Assert requesting a page is failing (with matching message)'
    response = await server_communication(url, data, params, method)
    assert response.code in range(400, 500)
    resp = json.loads(response.body)
    assert resp['message'] == msg
    return resp


async def assert_success(url, data=None, params=None, method='GET'):
    'Assert requesting a page is success'
    response = await server_communication(url, data, params, method)
    assert response.code == 200
    resp = json.loads(response.body)
    assert resp['success'] == True
    return resp


@pytest.mark.gen_test
async def test_health(http_client, base_url):
    'Test /healthz endpoint'
    response = await http_client.fetch(base_url + '/healthz')
    assert response.code == 200
    assert json.loads(response.body)['success']


@pytest.mark.gen_test
async def test_home(http_client, base_url):
    'Test homepage, favicon, etc.'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'none'
    response = await server_communication('/api/')
    assert response.code == 200
    assert response.body.decode().startswith('<!doctype html>')
    response = await server_communication('/api/favicon.ico')
    assert response.code == 200
    assert response.body.startswith(b'\x89PNG')
    response = await server_communication('/api/masonry.min.js')
    assert response.code == 200
    assert 'Masonry' in response.body.decode()
    response = await server_communication('/api/random-page')
    assert response.code == 404
    assert '<h1>404 Not Found</h1>\n' in response.body.decode()


@pytest.mark.gen_test
async def test_init(http_client, base_url):
    'Clear database'
    url = '/api/initialize-Data6ase'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'none'
    assert (await assert_success(url, params={'action': 'clear'}))[
        'message'
    ] == 'done'
    assert (await assert_success(url, params={'action': 'init'}))[
        'message'
    ] == 'done'
    await assert_success(url, params={'action': 'dump'})
    await assert_fail(
        url,
        params={'action': 'walk'},
        msg='action should be clear, init, or dump',
    )
    response = await server_communication(
        url, params={'action': 'dump', 'human-readable': 'true'}
    )
    assert response.code == 200
    assert 'masonry.min.js' in response.body.decode()


@pytest.mark.gen_test
async def test_list_courses(http_client, base_url):
    'Test GET /api/courses'
    url = '/api/courses'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    assert (await assert_success(url))['courses'] == ['course1']
    user = 'abigail'
    assert (await assert_success(url))['courses'] == ['course2']
    user = 'lawrence'
    assert (await assert_success(url))['courses'] == ['course1']
    user = 'eric'
    assert (await assert_success(url))['courses'] == ['course2']
    user = 'root'
    assert (await assert_success(url))['courses'] == ['course1', 'course2']


@pytest.mark.gen_test
async def test_add_course(http_client, base_url):
    'Test POST /api/course/<course_id>'
    url = '/api/course/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'eric'
    await assert_fail(
        url + 'course3', method='POST', msg='Permission denied (not admin)'
    )
    user = 'root'
    await assert_success(url + 'course3', method='POST')
    assert (await assert_success('/api/instructors/course3'))[
        'instructors'
    ] == []
    await assert_success(url + 'course3', method='DELETE')
    await assert_fail(
        url + 'course3',
        params={'instructors': '"root"]'},
        method='POST',
        msg='Instructors cannot be JSON decoded',
    )
    await assert_success(
        url + 'course3', params={'instructors': '["root"]'}, method='POST'
    )
    assert (await assert_success('/api/instructors/course3'))[
        'instructors'
    ] == [
        {
            'username': 'root',
            'first_name': None,
            'last_name': None,
            'email': None,
        }
    ]
    await assert_fail(
        url + 'course3', method='POST', msg='Course already exists'
    )
    # change owner to eric
    await assert_success(
        '/api/instructor/course3/eric',
        method='POST',
        data={'first_name': '', 'last_name': '', 'email': ''},
    )
    assert (await assert_success('/api/courses'))['courses'] == [
        'course1',
        'course2',
        'course3',
    ]
    await assert_success('/api/instructor/course3/root', method='DELETE')
    user = 'eric'
    assert (await assert_success('/api/courses'))['courses'] == [
        'course2',
        'course3',
    ]


@pytest.mark.gen_test
async def test_add_instructor(http_client, base_url):
    'Test POST /api/instructor/<course_id>/<instructor_id>'
    url = '/api/instructor/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'eric'
    await assert_fail(
        url + 'course2/lawrence',
        method='POST',
        msg='Permission denied (not course instructor)',
    )
    user = 'root'
    await assert_fail(
        url + 'course9/lawrence', method='POST', msg='Course not found'
    )
    data = {}
    await assert_fail(
        url + 'course2/lawrence',
        data=data,
        method='POST',
        msg='Please supply first name',
    )
    data['first_name'] = 'lawrence_course2_first_name'
    await assert_fail(
        url + 'course2/lawrence',
        data=data,
        method='POST',
        msg='Please supply last name',
    )
    data['last_name'] = 'lawrence_course2_last_name'
    await assert_fail(
        url + 'course2/lawrence',
        data=data,
        method='POST',
        msg='Please supply email',
    )
    data['email'] = 'lawrence_course2_email'
    await assert_success(
        url + 'course2/lawrence', data=data, method='POST'
    )
    assert (
        len(
            (await assert_success('/api/instructors/course2'))[
                'instructors'
            ]
        )
        == 2
    )
    # Test changing instructor name
    user = 'abigail'
    await assert_fail(
        url + 'course2/lawrence',
        data=data,
        method='POST',
        msg='Permission denied (cannot modify other instructors)',
    )
    user = 'abigail'
    await assert_fail(
        url + 'course2/eric',
        data=data,
        method='POST',
        msg='Permission denied (cannot modify instructors)',
    )
    user = 'abigail'
    await assert_fail(
        url + 'course2/kevin',
        data=data,
        method='POST',
        msg='Permission denied (cannot modify instructors)',
    )
    user = 'lawrence'
    await assert_success(
        url + 'course2/lawrence', data=data, method='POST'
    )
    # Test updating student to instructor, and empty email
    data = {
        'first_name': 'lawrence_course1_first_name',
        'last_name': 'lawrence_course1_last_name',
        'email': '',
    }
    await assert_fail(
        url + 'course1/lawrence',
        data=data,
        method='POST',
        msg='Permission denied (not course instructor)',
    )
    user = 'root'
    await assert_success(
        url + 'course1/lawrence', data=data, method='POST'
    )
    assert (
        len(
            (await assert_success('/api/instructors/course1'))[
                'instructors'
            ]
        )
        == 2
    )
    assert (
        len((await assert_success('/api/students/course1'))['students'])
        == 0
    )
    # Test adding non-existing instructor
    data = {'first_name': '', 'last_name': '', 'email': ''}
    await assert_success(
        url + 'course3/instructor', data=data, method='POST'
    )


@pytest.mark.gen_test
async def test_get_instructor(http_client, base_url):
    'Test GET /api/instructor/<course_id>/<instructor_id>'
    url = '/api/instructor/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    await assert_fail(url + 'course9/lawrence', msg='Course not found')
    await assert_fail(
        url + 'course2/lawrence',
        msg='Permission denied (not related to course)',
    )
    user = 'eric'
    await assert_fail(url + 'course9/lawrence', msg='Course not found')
    resp1 = await assert_success(url + 'course2/lawrence')
    user = 'abigail'
    await assert_fail(url + 'course2/eric', msg='Instructor not found')
    resp2 = await assert_success(url + 'course2/lawrence')
    assert resp1 == resp2
    assert resp1['username'] == 'lawrence'
    assert resp1['first_name'] == 'lawrence_course2_first_name'
    assert resp1['last_name'] == 'lawrence_course2_last_name'
    assert resp1['email'] == 'lawrence_course2_email'
    user = 'lawrence'
    resp3 = await assert_success(url + 'course1/lawrence')
    assert resp3['username'] == 'lawrence'
    assert resp3['first_name'] == 'lawrence_course1_first_name'
    assert resp3['last_name'] == 'lawrence_course1_last_name'
    assert resp3['email'] == ''


@pytest.mark.gen_test
async def test_delete_instructor(http_client, base_url):
    'Test DELETE /api/instructor/<course_id>/<instructor_id>'
    url = '/api/instructor/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'abigail'
    await assert_fail(
        url + 'course2/lawrence',
        method='DELETE',
        msg='Permission denied (not admin)',
    )
    user = 'root'
    await assert_fail(
        url + 'course9/lawrence', method='DELETE', msg='Course not found'
    )
    await assert_fail(
        url + 'course2/eric', method='DELETE', msg='Instructor not found'
    )
    await assert_success(url + 'course2/lawrence', method='DELETE')
    await assert_success(url + 'course1/kevin', method='DELETE')
    await assert_success(
        url + 'course1/kevin',
        method='POST',
        data={'first_name': '', 'last_name': '', 'email': ''},
    )


@pytest.mark.gen_test
async def test_list_instructors(http_client, base_url):
    'Test GET /api/instructors/<course_id>'
    url = '/api/instructors/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    await assert_fail(url + 'course9', msg='Course not found')
    await assert_fail(
        url + 'course2', msg='Permission denied (not related to course)'
    )
    user = 'eric'
    resp1 = (await assert_success(url + 'course2'))['instructors']
    user = 'abigail'
    resp2 = (await assert_success(url + 'course2'))['instructors']
    assert resp1 == resp2
    assert len(resp1) == 1
    assert resp1[0]['username'] == 'abigail'
    assert resp1[0]['first_name'] is None
    assert resp1[0]['last_name'] is None
    assert resp1[0]['email'] is None


@pytest.mark.gen_test
async def test_add_student(http_client, base_url):
    'Test POST /api/student/<course_id>/<student_id>'
    url = '/api/student/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'eric'
    await assert_fail(
        url + 'course9/lawrence', method='POST', msg='Course not found'
    )
    await assert_fail(
        url + 'course2/lawrence',
        method='POST',
        msg='Permission denied (not course instructor)',
    )
    user = 'abigail'
    data = {}
    await assert_fail(
        url + 'course2/lawrence',
        data=data,
        method='POST',
        msg='Please supply first name',
    )
    data['first_name'] = 'lawrence_course2_first_name'
    await assert_fail(
        url + 'course2/lawrence',
        data=data,
        method='POST',
        msg='Please supply last name',
    )
    data['last_name'] = 'lawrence_course2_last_name'
    await assert_fail(
        url + 'course2/lawrence',
        data=data,
        method='POST',
        msg='Please supply email',
    )
    data['email'] = 'lawrence_course2_email'
    await assert_success(
        url + 'course2/lawrence', data=data, method='POST'
    )
    assert (
        len((await assert_success('/api/students/course2'))['students'])
        == 2
    )
    # Test updating instructor to student, and empty email
    await assert_fail(
        url + 'course2/abigail',
        data=data,
        method='POST',
        msg='Cannot add instructor as student',
    )
    user = 'kevin'
    data = {
        'first_name': 'lawrence_course1_first_name',
        'last_name': 'lawrence_course1_last_name',
        'email': '',
    }
    await assert_fail(
        url + 'course1/lawrence',
        data=data,
        method='POST',
        msg='Cannot add instructor as student',
    )
    assert (
        len(
            (await assert_success('/api/instructors/course1'))[
                'instructors'
            ]
        )
        == 2
    )
    assert (
        len((await assert_success('/api/students/course1'))['students'])
        == 0
    )
    user = 'root'
    await assert_success(
        '/api/instructor/course1/lawrence', method='DELETE'
    )
    user = 'kevin'
    await assert_success(
        url + 'course1/lawrence', data=data, method='POST'
    )
    assert (
        len(
            (await assert_success('/api/instructors/course1'))[
                'instructors'
            ]
        )
        == 1
    )
    assert (
        len((await assert_success('/api/students/course1'))['students'])
        == 1
    )
    # Test adding non-existing instructor
    user = 'eric'
    data = {'first_name': '', 'last_name': '', 'email': ''}
    await assert_success(url + 'course3/student', data=data, method='POST')


@pytest.mark.gen_test
async def test_get_student(http_client, base_url):
    'Test GET /api/student/<course_id>/<student_id>'
    url = '/api/student/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    await assert_fail(url + 'course9/lawrence', msg='Course not found')
    await assert_fail(
        url + 'course2/lawrence',
        msg='Permission denied (not course instructor)',
    )
    user = 'eric'
    await assert_fail(
        url + 'course2/lawrence',
        msg='Permission denied (not course instructor)',
    )
    user = 'abigail'
    await assert_fail(url + 'course2/abigail', msg='Student not found')
    resp = await assert_success(url + 'course2/lawrence')
    assert resp['username'] == 'lawrence'
    assert resp['first_name'] == 'lawrence_course2_first_name'
    assert resp['last_name'] == 'lawrence_course2_last_name'
    assert resp['email'] == 'lawrence_course2_email'


@pytest.mark.gen_test
async def test_delete_student(http_client, base_url):
    'Test DELETE /api/student/<course_id>/<student_id>'
    url = '/api/student/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'eric'
    await assert_fail(
        url + 'course9/lawrence', method='DELETE', msg='Course not found'
    )
    await assert_fail(
        url + 'course2/lawrence',
        method='DELETE',
        msg='Permission denied (not course instructor)',
    )
    user = 'abigail'
    await assert_fail(
        url + 'course2/kevin', method='DELETE', msg='Student not found'
    )
    await assert_success(url + 'course2/lawrence', method='DELETE')


@pytest.mark.gen_test
async def test_add_students(http_client, base_url):
    'Test POST /api/students/<course_id>'
    url = '/api/students/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    await assert_fail(url + 'course9', msg='Course not found')
    await assert_fail(
        url + 'course2',
        method='POST',
        msg='Permission denied (not course instructor)',
    )
    await assert_fail(
        url + 'course1', method='POST', data={}, msg='Please supply students'
    )
    await assert_fail(
        url + 'course1',
        method='POST',
        data={'students': '"'},
        msg='Students cannot be JSON decoded',
    )
    await assert_fail(
        url + 'course1',
        method='POST',
        data={'students': '12'},
        msg='Incorrect request format',
    )
    await assert_fail(
        url + 'course1',
        method='POST',
        data={'students': '[]'},
        msg='Please supply students',
    )
    await assert_fail(
        url + 'course1',
        method='POST',
        data={'students': '[1,2]'},
        msg='Incorrect request format',
    )
    students = [{'username': 'a', 'email': 'b', 'first_name': 'c'}]
    await assert_fail(
        url + 'course1',
        method='POST',
        data={'students': json.dumps(students)},
        msg='Incorrect request format',
    )
    students = [
        {'username': 'a', 'first_name': 'af', 'last_name': 'al', 'email': 'ae'},
        {'username': 'b', 'first_name': 'bf', 'last_name': 'bl', 'email': 'be'},
        {'username': 'c', 'first_name': 'cf', 'last_name': 'cl', 'email': 'ce'},
        {'username': 'd', 'first_name': 'df', 'last_name': 'dl', 'email': 'de'},
        {'username': 'e', 'first_name': '', 'last_name': '', 'email': ''},
        {'username': 'kevin', 'first_name': '', 'last_name': '', 'email': ''},
        {
            'username': 'lawrence',
            'first_name': '',
            'last_name': '',
            'email': '',
        },
    ]
    resp = await assert_success(
        url + 'course1', method='POST', data={'students': json.dumps(students)}
    )
    expected = [
        {'username': 'a', 'success': True},
        {'username': 'b', 'success': True},
        {'username': 'c', 'success': True},
        {'username': 'd', 'success': True},
        {'username': 'e', 'success': True},
        {
            'username': 'kevin',
            'success': False,
            'message': 'Cannot add instructor as student',
        },
        {'username': 'lawrence', 'success': True},
    ]
    assert resp['status'] == expected
    resp = (await assert_success(url + 'course1'))['students']
    assert len(resp) == 6
    for i in resp:
        assert i in students


@pytest.mark.gen_test
async def test_list_students(http_client, base_url):
    'Test GET /api/students/<course_id>'
    url = '/api/students/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    await assert_fail(url + 'course9', msg='Course not found')
    await assert_fail(
        url + 'course2', msg='Permission denied (not course instructor)'
    )
    user = 'eric'
    await assert_fail(
        url + 'course2', msg='Permission denied (not course instructor)'
    )
    user = 'abigail'
    resp = (await assert_success(url + 'course2'))['students']
    assert len(resp) == 1
    assert resp[0]['username'] == 'eric'
    assert resp[0]['first_name'] is None
    assert resp[0]['last_name'] is None
    assert resp[0]['email'] is None


@pytest.mark.gen_test
async def test_list_assignments(http_client, base_url):
    'Test GET /api/assignments/<course_id>'
    url = '/api/assignments/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    await assert_fail(
        url + 'course2', msg='Permission denied (not related to course)'
    )
    user = 'abigail'
    assert (await assert_success(url + 'course2'))['assignments'] == [
        'assignment2a',
        'assignment2b',
    ]
    user = 'lawrence'
    await assert_fail(
        url + 'course2', msg='Permission denied (not related to course)'
    )
    user = 'eric'
    assert (await assert_success(url + 'course2'))['assignments'] == [
        'assignment2a',
        'assignment2b',
    ]
    await assert_fail(url + 'jkl', msg='Course not found')


@pytest.mark.gen_test
async def test_download_assignment(http_client, base_url):
    'Test GET /api/assignment/<course_id>/<assignment_id>'
    url = '/api/assignment/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    files = (await assert_success(url + 'course1/challenge'))['files']
    assert files[0]['path'] == 'file2'
    assert base64.b64decode(files[0]['content'].encode()) == b'22222'
    assert files[0]['checksum'] == hashlib.md5(b'22222').hexdigest()
    await assert_fail(url + 'jkl/challenger', msg='Course not found')
    await assert_fail(
        url + 'course1/challenger', msg='Assignment not found'
    )
    # Check list_only
    files = (
        await assert_success(url + 'course1/challenge?list_only=true')
    )['files']
    assert set(files[0]) == {'path', 'checksum'}
    assert files[0]['path'] == 'file2'
    assert files[0]['checksum'] == hashlib.md5(b'22222').hexdigest()
    user = 'eric'
    await assert_fail(
        url + 'course1/challenge',
        msg='Permission denied (not related to course)',
    )


@pytest.mark.gen_test
async def test_release_assignment(http_client, base_url):
    'Test POST /api/assignment/<course_id>/<assignment_id>'
    url = '/api/assignment/'
    global hc, bu, user
    hc, bu = http_client, base_url
    data = {
        'files': json.dumps(
            [
                {'path': 'a', 'content': 'amtsCg=='},
                {'path': 'b', 'content': 'amtsCg=='},
            ]
        )
    }
    user = 'kevin'
    await assert_fail(
        url + 'jkl/challenger', method='POST', data=data, msg='Course not found'
    )
    await assert_fail(
        url + 'course1/challenger', method='POST', msg='Please supply files'
    )
    await assert_success(
        url + 'course1/challenger', method='POST', data=data
    )
    await assert_fail(
        url + 'course1/challenger',
        method='POST',
        data=data,
        msg='Assignment already exists',
    )
    data['files'] = json.dumps([{'path': 'a', 'content': 'amtsCg'}])
    await assert_fail(
        url + 'course1/challenges',
        method='POST',
        data=data,
        msg='Content cannot be base64 decoded',
    )
    for pathname in ['/a', '/', '', '../etc', 'a/./a.py', 'a/.']:
        data['files'] = json.dumps([{'path': pathname, 'content': ''}])
        await assert_fail(
            url + 'course1/challenges',
            method='POST',
            data=data,
            msg='Illegal path',
        )
    user = 'abigail'
    await assert_fail(
        url + 'course1/challenger',
        method='POST',
        data=data,
        msg='Permission denied (not course instructor)',
    )
    user = 'lawrence'
    await assert_fail(
        url + 'course1/challenger',
        method='POST',
        data=data,
        msg='Permission denied (not course instructor)',
    )
    user = 'eric'
    await assert_fail(
        url + 'course1/challenger',
        method='POST',
        data=data,
        msg='Permission denied (not course instructor)',
    )


@pytest.mark.gen_test
async def test_delete_assignment(http_client, base_url):
    'Test DELETE /api/assignment/<course_id>/<assignment_id>'
    url = '/api/assignment/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'lawrence'
    await assert_fail(
        url + 'course1/challenger',
        method='DELETE',
        msg='Permission denied (not course instructor)',
    )
    user = 'kevin'
    await assert_fail(
        url + 'jkl/challenger', method='DELETE', msg='Course not found'
    )
    await assert_fail(
        url + 'course1/challengers', method='DELETE', msg='Assignment not found'
    )
    await assert_success(url + 'course1/challenger')
    await assert_success(url + 'course1/challenger', method='DELETE')
    await assert_fail(
        url + 'course1/challenger', msg='Assignment not found'
    )


@pytest.mark.gen_test
async def test_list_submissions(http_client, base_url):
    'Test GET /api/submissions/<course_id>/<assignment_id>'
    url = '/api/submissions/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    await assert_fail(url + 'jkl/challenge', msg='Course not found')
    await assert_fail(
        url + 'course1/challenges', msg='Assignment not found'
    )
    result = await assert_success(url + 'course1/challenge')
    assert len(result['submissions']) == 2
    assert set(result['submissions'][0]) == {'student_id', 'timestamp'}
    assert result['submissions'][0]['student_id'] == 'lawrence'
    assert result['submissions'][1]['student_id'] == 'lawrence'
    user = 'abigail'
    result = await assert_success(url + 'course2/assignment2a')
    assert len(result['submissions']) == 0
    user = 'eric'
    await assert_fail(
        url + 'course1/challenges',
        msg='Permission denied (not course instructor)',
    )
    await assert_fail(
        url + 'course2/assignment2a',
        msg='Permission denied (not course instructor)',
    )


@pytest.mark.gen_test
async def test_list_student_submission(http_client, base_url):
    'Test GET /api/submissions/<course_id>/<assignment_id>/<student_id>'
    url = '/api/submissions/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    await assert_fail(url + 'jkl/challenge/st', msg='Course not found')
    await assert_fail(
        url + 'course1/challenges/st', msg='Assignment not found'
    )
    await assert_fail(
        url + 'course1/challenge/st', msg='Student not found'
    )
    result = await assert_success(url + 'course1/challenge/lawrence')
    assert len(result['submissions']) == 2
    assert set(result['submissions'][0]) == {'student_id', 'timestamp'}
    user = 'eric'
    result = await assert_success(url + 'course2/assignment2a/eric')
    assert len(result['submissions']) == 0
    user = 'kevin'
    await assert_fail(
        url + 'course2/assignment2a/eric',
        msg='Permission denied (not course instructor)',
    )
    user = 'abigail'
    await assert_fail(
        url + 'course1/challenge/lawrence',
        msg='Permission denied (not course instructor)',
    )
    user = 'lawrence'
    await assert_success(url + 'course1/challenge/lawrence')
    user = 'eric'
    await assert_fail(
        url + 'course1/challenge/lawrence',
        msg='Permission denied (not course instructor)',
    )


@pytest.mark.gen_test
async def test_submit_assignment(http_client, base_url):
    'Test POST /api/submission/<course_id>/<assignment_id>'
    url = '/api/submission/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    data = {
        'files': json.dumps(
            [
                {'path': 'a', 'content': 'amtsCg=='},
                {'path': 'b', 'content': 'amtsCg=='},
            ]
        )
    }
    await assert_fail(
        url + 'jkl/challenge', method='POST', msg='Course not found'
    )
    await assert_fail(
        url + 'course1/challenges', method='POST', msg='Assignment not found'
    )
    user = 'lawrence'
    await assert_fail(
        url + 'course1/challenge', method='POST', msg='Please supply files'
    )
    resp1 = await assert_success(
        url + 'course1/challenge', method='POST', data=data
    )
    ts1 = MyHelpers().strptime(resp1['timestamp'])
    data['files'] = json.dumps([{'path': 'a', 'content': 'amtsCg=='}])
    resp2 = await assert_success(
        url + 'course1/challenge', method='POST', data=data
    )
    ts2 = MyHelpers().strptime(resp2['timestamp'])
    assert ts1 < ts2
    assert ts2 < ts1 + datetime.timedelta(seconds=1)
    data['files'] = json.dumps([{'path': 'a', 'content': 'amtsCg'}])
    await assert_fail(
        url + 'course1/challenge',
        method='POST',
        data=data,
        msg='Content cannot be base64 decoded',
    )
    data['files'] = 'a-random-string'
    await assert_fail(
        url + 'course1/challenge',
        method='POST',
        data=data,
        msg='Files cannot be JSON decoded',
    )
    user = 'kevin'
    result = await assert_success('/api/submissions/course1/challenge')
    assert len(result['submissions']) == 4  # 2 from init, 2 from this
    user = 'eric'
    await assert_fail(
        url + 'course1/challenge',
        method='POST',
        msg='Permission denied (not related to course)',
    )


@pytest.mark.gen_test
async def test_download_submission(http_client, base_url):
    'Test GET /api/submission/<course_id>/<assignment_id>/<student_id>'
    url = '/api/submission/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    await assert_fail(url + 'jkl/challenge/st', msg='Course not found')
    await assert_fail(
        url + 'course1/challenges/st', msg='Assignment not found'
    )
    await assert_fail(
        url + 'course1/challenge/st', msg='Student not found'
    )
    # Test get latest
    result = await assert_success(url + 'course1/challenge/lawrence')
    files = result['files']
    assert len(files) == 1
    file_obj = next(filter(lambda x: x['path'] == 'a', files), None)
    assert base64.b64decode(file_obj['content'].encode()) == b'jkl\n'
    assert file_obj['checksum'] == hashlib.md5(b'jkl\n').hexdigest()
    user = 'abigail'
    await assert_fail(
        url + 'course2/assignment2a/eric', msg='Submission not found'
    )
    # Test get latest with list_only
    user = 'kevin'
    result = await assert_success(
        url + 'course1/challenge/lawrence', params={'list_only': 'true'}
    )
    files = result['files']
    assert len(files) == 1
    assert set(files[0]) == {'path', 'checksum'}
    assert files[0]['path'] == 'a'
    assert files[0]['checksum'] == hashlib.md5(b'jkl\n').hexdigest()
    # Test timestamp
    result = await assert_success(
        '/api/submissions/course1/challenge/lawrence'
    )
    timestamp = sorted(map(lambda x: x['timestamp'], result['submissions']))[0]
    result = await assert_success(
        url + 'course1/challenge/lawrence', params={'timestamp': timestamp}
    )
    files = result['files']
    assert len(files) == 1
    file_obj = next(filter(lambda x: x['path'] == 'file3', files), None)
    assert base64.b64decode(file_obj['content'].encode()) == b'33333'
    assert file_obj['checksum'] == hashlib.md5(b'33333').hexdigest()
    # Test timestamp with list_only
    result = await assert_success(
        '/api/submissions/course1/challenge/lawrence'
    )
    timestamp = sorted(map(lambda x: x['timestamp'], result['submissions']))[0]
    result = await assert_success(
        url + 'course1/challenge/lawrence',
        params={'timestamp': timestamp, 'list_only': 'true'},
    )
    files = result['files']
    assert len(files) == 1
    file_obj = next(filter(lambda x: x['path'] == 'file3', files), None)
    assert 'content' not in file_obj
    assert file_obj['checksum'] == hashlib.md5(b'33333').hexdigest()
    # Test timestamp not found
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f %Z')
    await assert_fail(
        url + 'course1/challenge/lawrence',
        params={'timestamp': timestamp},
        msg='Submission not found',
    )
    # Test permission
    user = 'eric'
    await assert_fail(
        url + 'course2/assignment2a/eric',
        msg='Permission denied (not course instructor)',
    )


@pytest.mark.gen_test
async def test_upload_feedback(http_client, base_url):
    'Test POST /api/feedback/<course_id>/<assignment_id>/<student_id>'
    url = '/api/feedback/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    data = {
        'files': json.dumps(
            [
                {'path': 'a', 'content': 'amtsCg=='},
                {'path': 'b', 'content': 'amtsCg=='},
            ]
        ),
        'timestamp': '2020-01-01 00:00:00.000000 ',
    }
    await assert_fail(
        url + 'jkl/challenge/st',
        method='POST',
        data=data,
        msg='Course not found',
    )
    await assert_fail(
        url + 'course1/challenges/st',
        method='POST',
        data=data,
        msg='Assignment not found',
    )
    await assert_fail(
        url + 'course1/challenge/st',
        method='POST',
        data=data,
        msg='Student not found',
    )
    await assert_success(
        url + 'course1/challenge/lawrence', method='POST', data=data
    )
    data['files'] = json.dumps([{'path': 'c', 'content': 'amtsCf=='}])
    await assert_success(
        url + 'course1/challenge/lawrence', method='POST', data=data
    )
    await assert_fail(
        url + 'course1/challenge/lawrence',
        method='POST',
        data={},
        msg='Please supply timestamp',
    )
    await assert_fail(
        url + 'course1/challenge/lawrence',
        method='POST',
        data={'timestamp': 'a'},
        msg='Time format incorrect',
    )
    user = 'abigail'
    await assert_fail(
        url + 'course2/assignment2a/eric',
        method='POST',
        data=data,
        msg='Submission not found',
    )
    await assert_fail(
        url + 'course2/assignment2a/eric',
        method='POST',
        data={'timestamp': data['timestamp']},
        msg='Submission not found',
    )
    user = 'eric'
    await assert_fail(
        url + 'course2/assignment2a/eric',
        method='POST',
        data=data,
        msg='Permission denied (not course instructor)',
    )


@pytest.mark.gen_test
async def test_download_feedback(http_client, base_url):
    'Test GET /api/feedback/<course_id>/<assignment_id>/<student_id>'
    url = '/api/feedback/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    await assert_fail(url + 'jkl/challenge/st', msg='Course not found')
    await assert_fail(
        url + 'course1/challenges/st', msg='Assignment not found'
    )
    await assert_fail(
        url + 'course1/challenge/st', msg='Student not found'
    )
    meta = await assert_success(
        '/api/submission/course1/challenge/lawrence'
    )
    timestamp = meta['timestamp']
    await assert_fail(
        url + 'course1/challenge/lawrence',
        params={},
        msg='Please supply timestamp',
    )
    await assert_fail(
        url + 'course1/challenge/lawrence',
        params={'timestamp': 'a'},
        msg='Time format incorrect',
    )
    user = 'eric'
    await assert_fail(
        url + 'course2/assignment2a/eric',
        params={'timestamp': timestamp},
        msg='Submission not found',
    )
    user = 'kevin'
    feedback = await assert_success(
        url + 'course1/challenge/lawrence', params={'timestamp': timestamp}
    )
    assert feedback['files'] == []
    # Submit again ('amtsDg==' is 'jkl\x0e')
    data = {
        'files': json.dumps([{'path': 'a', 'content': 'amtsDg=='}]),
        'timestamp': timestamp,
    }
    await assert_success(
        url + 'course1/challenge/lawrence', method='POST', data=data
    )
    # Fetch again
    feedback = await assert_success(
        url + 'course1/challenge/lawrence', params={'timestamp': timestamp}
    )
    assert len(feedback['files']) == 1
    assert feedback['files'][0]['path'] == 'a'
    file_obj = feedback['files'][0]
    assert base64.b64decode(file_obj['content'].encode()) == b'jkl\x0e'
    assert file_obj['checksum'] == hashlib.md5(b'jkl\x0e').hexdigest()
    # Again, submit again ('nmtsDg==' is 'nkl\x0e')
    data = {
        'files': json.dumps([{'path': 'a', 'content': 'bmtsDg=='}]),
        'timestamp': timestamp,
    }
    await assert_success(
        url + 'course1/challenge/lawrence', method='POST', data=data
    )
    # Again, fetch again
    feedback = await assert_success(
        url + 'course1/challenge/lawrence', params={'timestamp': timestamp}
    )
    assert len(feedback['files']) == 1
    file_obj = feedback['files'][0]
    assert file_obj['path'] == 'a'
    assert base64.b64decode(file_obj['content'].encode()) == b'nkl\x0e'
    assert file_obj['checksum'] == hashlib.md5(b'nkl\x0e').hexdigest()
    # Check list_only
    feedback = await assert_success(
        url + 'course1/challenge/lawrence',
        params={'timestamp': timestamp, 'list_only': 'true'},
    )
    assert len(feedback['files']) == 1
    assert set(feedback['files'][0]) == {'path', 'checksum'}
    assert file_obj['checksum'] == hashlib.md5(b'nkl\x0e').hexdigest()
    assert feedback['files'][0]['path'] == 'a'
    # Permission check
    user = 'kevin'
    await assert_fail(
        url + 'course1/challenge/lawrence', msg='Please supply timestamp'
    )
    user = 'abigail'
    await assert_fail(
        url + 'course1/challenge/lawrence',
        msg='Permission denied (not course instructor)',
    )
    user = 'lawrence'
    await assert_fail(
        url + 'course1/challenge/lawrence', msg='Please supply timestamp'
    )
    user = 'eric'
    await assert_fail(
        url + 'course1/challenge/lawrence',
        msg='Permission denied (not course instructor)',
    )


@pytest.mark.gen_test
async def test_remove_course(http_client, base_url):
    'Test DELETE /api/course/<course_id>'
    url = '/api/course/'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'kevin'
    await assert_fail(
        url + 'course1', method='DELETE', msg='Permission denied (not admin)'
    )
    user = 'root'
    await assert_success(url + 'course1', method='DELETE')
    await assert_success(url + 'course2', method='DELETE')
    await assert_success(url + 'course3', method='DELETE')
    await assert_fail(
        url + 'course4', method='DELETE', msg='Course not found'
    )
    resp = await assert_success(
        '/api/initialize-Data6ase', params={'action': 'dump'}
    )
    # All other tables should be empty
    assert set(resp.keys()) == {'success', 'users'}


@pytest.mark.gen_test
async def test_corner_case(http_client, base_url):
    'Test corner cases to increase coverage'
    global hc, bu, user
    hc, bu = http_client, base_url
    init_url = '/api/initialize-Data6ase'
    user = 'none'
    await assert_success(init_url, params={'action': 'clear'})
    await assert_success(init_url, params={'action': 'init'})
    # Long file extension
    user = 'eric'
    data = {
        'files': json.dumps(
            [{'path': 'a.abcdefghijklmnopqrstuvw', 'content': 'amtsCg=='}]
        )
    }
    url = '/api/submission/course2/assignment2a'
    await assert_success(url, method='POST', data=data)
    user = 'abigail'
    assert (await assert_success(url + '/eric'))['files'][0][
        'path'
    ] == 'a.abcdefghijklmnopqrstuvw'
    # File name conflict
    ori_filename_create = MyHelpers.filename_create
    counter = 0

    def mock_filename_create(self, filename):
        nonlocal counter
        counter += 1
        return str(counter**2 % 10) + '.tmp'

    MyHelpers.filename_create = mock_filename_create
    for i in range(100):
        # There must be a conflict within 10 tries
        assert i <= 10
        params = {'user': 'eric'}
        response = await server_communication(url, data, params, 'POST')
        resp = json.loads(response.body)
        if response.code == 200:
            assert resp['success'] == True
            continue
        assert resp['success'] == False
        assert resp['message'] == 'Internal server error (filename conflict)'
        assert i > 2
        break
    MyHelpers.filename_create = ori_filename_create


@pytest.mark.gen_test
async def test_nodebug(http_client, base_url):
    'Test ngshare with debug-mode off'
    application.debug = False
    url = '/api/initialize-Data6ase'
    global hc, bu, user
    hc, bu = http_client, base_url
    user = 'none'
    await assert_fail(
        url, params={'action': 'clear'}, msg='Debug mode is off'
    )
    await assert_fail(
        url, params={'action': 'init'}, msg='Debug mode is off'
    )
    response = await server_communication('/api/random-page')
    assert response.code == 404
    assert response.body.decode() == '<h1>404 Not Found</h1>\n'


def test_api_prefix():
    'Test throwing an error when API prefix is illegal'
    # does not start with '/'
    with pytest.raises(ValueError):
        main(['--prefix', 'api/'])
    # does not end with '/'
    with pytest.raises(ValueError):
        main(['--prefix', '/api'])
    # starts with /healthz/'
    with pytest.raises(ValueError):
        main(['--prefix', '/healthz/'])


def test_notimpl():
    'Test NotImplementedError etc'
    with pytest.raises(NotImplementedError):
        MyHelpers().json_error(404, 'Not Found')
    assert MockAuth().get_login_url().startswith('http')


def test_clean():
    'Clean temporary files'
    global db_name, storage_name
    os.remove(db_name)
    shutil.rmtree(storage_name)
