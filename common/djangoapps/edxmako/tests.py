
from mock import patch, Mock
import unittest
import ddt

from django.conf import settings
from django.http import HttpResponse
from django.test import TestCase
from django.test.utils import override_settings
from django.test.client import RequestFactory
from django.core.urlresolvers import reverse
import edxmako.middleware
from edxmako.middleware import get_template_request_context
from edxmako import add_lookup, LOOKUP
from edxmako.shortcuts import (
    marketing_link,
    is_marketing_link_set,
    is_any_marketing_link_set,
    render_to_string,
    open_source_footer_context_processor
)
from student.tests.factories import UserFactory
from util.testing import UrlResetMixin


@ddt.ddt
class ShortcutsTests(UrlResetMixin, TestCase):
    """
    Test the edxmako shortcuts file
    """
    @override_settings(MKTG_URLS={'ROOT': 'dummy-root', 'ABOUT': '/about-us'})
    @override_settings(MKTG_URL_LINK_MAP={'ABOUT': 'login'})
    def test_marketing_link(self):
        # test marketing site on
        with patch.dict('django.conf.settings.FEATURES', {'ENABLE_MKTG_SITE': True}):
            expected_link = 'dummy-root/about-us'
            link = marketing_link('ABOUT')
            self.assertEquals(link, expected_link)
        # test marketing site off
        with patch.dict('django.conf.settings.FEATURES', {'ENABLE_MKTG_SITE': False}):
            # we are using login because it is common across both cms and lms
            expected_link = reverse('login')
            link = marketing_link('ABOUT')
            self.assertEquals(link, expected_link)

    @override_settings(MKTG_URLS={'ROOT': 'dummy-root', 'ABOUT': '/about-us'})
    @override_settings(MKTG_URL_LINK_MAP={'ABOUT': 'login'})
    def test_is_marketing_link_set(self):
        # test marketing site on
        with patch.dict('django.conf.settings.FEATURES', {'ENABLE_MKTG_SITE': True}):
            self.assertTrue(is_marketing_link_set('ABOUT'))
            self.assertFalse(is_marketing_link_set('NOT_CONFIGURED'))
        # test marketing site off
        with patch.dict('django.conf.settings.FEATURES', {'ENABLE_MKTG_SITE': False}):
            self.assertTrue(is_marketing_link_set('ABOUT'))
            self.assertFalse(is_marketing_link_set('NOT_CONFIGURED'))

    @override_settings(MKTG_URLS={'ROOT': 'dummy-root', 'ABOUT': '/about-us'})
    @override_settings(MKTG_URL_LINK_MAP={'ABOUT': 'login'})
    def test_is_any_marketing_link_set(self):
        # test marketing site on
        with patch.dict('django.conf.settings.FEATURES', {'ENABLE_MKTG_SITE': True}):
            self.assertTrue(is_any_marketing_link_set(['ABOUT']))
            self.assertTrue(is_any_marketing_link_set(['ABOUT', 'NOT_CONFIGURED']))
            self.assertFalse(is_any_marketing_link_set(['NOT_CONFIGURED']))
        # test marketing site off
        with patch.dict('django.conf.settings.FEATURES', {'ENABLE_MKTG_SITE': False}):
            self.assertTrue(is_any_marketing_link_set(['ABOUT']))
            self.assertTrue(is_any_marketing_link_set(['ABOUT', 'NOT_CONFIGURED']))
            self.assertFalse(is_any_marketing_link_set(['NOT_CONFIGURED']))

    @ddt.data((True, None), (False, None))
    @ddt.unpack
    def test_edx_footer(self, expected_result, _):
        with patch.dict('django.conf.settings.FEATURES', {
            'IS_EDX_DOMAIN': expected_result
        }):
            result = open_source_footer_context_processor({})
            self.assertEquals(expected_result, result.get('IS_EDX_DOMAIN'))


class AddLookupTests(TestCase):
    """
    Test the `add_lookup` function.
    """
    @patch('edxmako.LOOKUP', {})
    def test_with_package(self):
        add_lookup('test', 'management', __name__)
        dirs = LOOKUP['test'].directories
        self.assertEqual(len(dirs), 1)
        self.assertTrue(dirs[0].endswith('management'))


class MakoMiddlewareTest(TestCase):
    """
    Test MakoMiddleware.
    """

    def setUp(self):
        super(MakoMiddlewareTest, self).setUp()
        self.middleware = edxmako.middleware.MakoMiddleware()
        self.user = UserFactory.create()
        self.url = "/"
        self.request = RequestFactory().get(self.url)
        self.request.user = self.user
        self.response = Mock(spec=HttpResponse)

    def test_clear_request_context_variable(self):
        """
        Test the global variable requestcontext is cleared correctly
        when response middleware is called.
        """

        self.middleware.process_request(self.request)
        # requestcontext should not be None.
        self.assertIsNotNone(get_template_request_context())

        self.middleware.process_response(self.request, self.response)
        # requestcontext should be None.
        self.assertIsNone(get_template_request_context())

    @unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
    @patch("edxmako.middleware.REQUEST_CONTEXT")
    def test_render_to_string_when_no_global_context_lms(self, context_mock):
        """
        Test render_to_string() when makomiddleware has not initialized
        the threadlocal REQUEST_CONTEXT.context. This is meant to run in LMS.
        """
        del context_mock.context
        self.assertIn("this module is temporarily unavailable", render_to_string("courseware/error-message.html", None))

    @unittest.skipUnless(settings.ROOT_URLCONF == 'cms.urls', 'Test only valid in cms')
    @patch("edxmako.middleware.REQUEST_CONTEXT")
    def test_render_to_string_when_no_global_context_cms(self, context_mock):
        """
        Test render_to_string() when makomiddleware has not initialized
        the threadlocal REQUEST_CONTEXT.context. This is meant to run in CMS.
        """
        del context_mock.context
        self.assertIn("We're having trouble rendering your component", render_to_string("html_error.html", None))


def mako_middleware_process_request(request):
    """
    Initialize the global RequestContext variable
    edxmako.middleware.requestcontext using the request object.
    """
    mako_middleware = edxmako.middleware.MakoMiddleware()
    mako_middleware.process_request(request)
