"""
Tests for functionality in openedx/core/lib/courses.py.
"""

import ddt
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.factories import CourseFactory
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase

from ..courses import course_image_url


@ddt.ddt
class CourseImageTestCase(ModuleStoreTestCase):
    """Tests for course image URLs."""

    def verify_url(self, expected_url, actual_url):
        """
        Helper method for verifying the URL is as expected.
        """
        if not expected_url.startswith("/"):
            expected_url = "/" + expected_url
        self.assertEquals(expected_url, actual_url)

    def test_get_image_url(self):
        """Test image URL formatting."""
        course = CourseFactory.create()
        self.verify_url(
            unicode(course.id.make_asset_key('asset', course.course_image)),
            course_image_url(course)
        )

    def test_non_ascii_image_name(self):
        """ Verify that non-ascii image names are cleaned """
        course_image = u'before_\N{SNOWMAN}_after.jpg'
        course = CourseFactory.create(course_image=course_image)
        self.verify_url(
            unicode(course.id.make_asset_key('asset', course_image.replace(u'\N{SNOWMAN}', '_'))),
            course_image_url(course)
        )

    def test_spaces_in_image_name(self):
        """ Verify that image names with spaces in them are cleaned """
        course_image = u'before after.jpg'
        course = CourseFactory.create(course_image=u'before after.jpg')
        self.verify_url(
            unicode(course.id.make_asset_key('asset', course_image.replace(" ", "_"))),
            course_image_url(course)
        )

    @ddt.data(ModuleStoreEnum.Type.split, ModuleStoreEnum.Type.mongo)
    def test_empty_image_name(self, default_store):
        """ Verify that empty image names are cleaned """
        course_image = u''
        course = CourseFactory.create(course_image=course_image, default_store=default_store)
        self.assertEquals(
            course_image,
            course_image_url(course),
        )
