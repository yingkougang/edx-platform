"""
Tests of modulestore semantics: How do the interfaces methods of ModuleStore relate to each other?
"""

import ddt
import itertools
from collections import namedtuple

from xmodule.modulestore.tests.utils import (
    PureModulestoreTestCase, MongoModulestoreBuilder,
    SPLIT_MODULESTORE_SETUP
)
from xmodule.modulestore.exceptions import ItemNotFoundError
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.factories import CourseFactory
from xmodule.modulestore.draft_and_published import DIRECT_ONLY_CATEGORIES
from xblock.core import XBlock

DETACHED_BLOCK_TYPES = dict(XBlock.load_tagged_classes('detached'))

# These tests won't work with courses, since they're creating blocks inside courses
TESTABLE_BLOCK_TYPES = set(DIRECT_ONLY_CATEGORIES)
TESTABLE_BLOCK_TYPES.discard('course')

TestField = namedtuple('TestField', ['field_name', 'initial', 'updated'])


@ddt.ddt
class DirectOnlyCategorySemantics(PureModulestoreTestCase):
    """
    Verify the behavior of Direct Only items
    blocks intended to store snippets of course content.
    """

    __test__ = False

    DATA_FIELDS = {
        'about': TestField('data', '<div>test data</div>', '<div>different test data</div>'),
        'chapter': TestField('is_entrance_exam', True, False),
        'sequential': TestField('is_entrance_exam', True, False),
        'static_tab': TestField('data', '<div>test data</div>', '<div>different test data</div>'),
        'course_info': TestField('data', '<div>test data</div>', '<div>different test data</div>'),
    }

    def setUp(self):
        super(DirectOnlyCategorySemantics, self).setUp()
        self.course = CourseFactory.create(
            org='test_org',
            number='999',
            run='test_run',
            display_name='My Test Course',
            modulestore=self.store
        )

    def assertBlockDoesntExist(self, block_usage_key, draft=None):
        """
        Verify that loading ``block_usage_key`` raises an ItemNotFoundError.

        Arguments:
            block_usage_key: The xblock to check.
            draft (optional): If omitted, verify both published and draft branches.
                If True, verify only the draft branch. If False, verify only the
                published branch.
        """
        if draft is None or draft:
            with self.store.branch_setting(ModuleStoreEnum.Branch.draft_preferred):
                with self.assertRaises(ItemNotFoundError):
                    self.store.get_item(block_usage_key)

        if draft is None or not draft:
            with self.store.branch_setting(ModuleStoreEnum.Branch.published_only):
                with self.assertRaises(ItemNotFoundError):
                    self.store.get_item(block_usage_key)

    def assertBlockHasContent(self, block_usage_key, field_name, content, draft=None):
        """
        Assert that the block ``block_usage_key`` has the value ``content`` for ``field_name``
        when it is loaded.

        Arguments:
            block_usage_key: The xblock to check.
            field_name (string): The name of the field to check.
            content: The value to assert is in the field.
            draft (optional): If omitted, verify both published and draft branches.
                If True, verify only the draft branch. If False, verify only the
                published branch.
        """
        if draft is None or not draft:
            with self.store.branch_setting(ModuleStoreEnum.Branch.published_only):
                target_block = self.store.get_item(
                    block_usage_key,
                )
                self.assertEquals(content, target_block.fields[field_name].read_from(target_block))

        if draft is None or draft:
            with self.store.branch_setting(ModuleStoreEnum.Branch.draft_preferred):
                target_block = self.store.get_item(
                    block_usage_key,
                )
                self.assertEquals(content, target_block.fields[field_name].read_from(target_block))

    def assertParentOf(self, parent_usage_key, child_usage_key, draft=None):
        """
        Assert that the block ``parent_usage_key`` has ``child_usage_key`` listed
        as one of its ``.children``.

        Arguments:
            parent_usage_key: The xblock to check as a parent.
            child_usage_key: The xblock to check as a child.
            draft (optional): If omitted, verify both published and draft branches.
                If True, verify only the draft branch. If False, verify only the
                published branch.
        """
        if draft is None or not draft:
            with self.store.branch_setting(ModuleStoreEnum.Branch.published_only):
                parent_block = self.store.get_item(
                    parent_usage_key,
                )
                self.assertIn(child_usage_key, parent_block.children)

        if draft is None or draft:
            with self.store.branch_setting(ModuleStoreEnum.Branch.draft_preferred):
                parent_block = self.store.get_item(
                    parent_usage_key,
                )
                self.assertIn(child_usage_key, parent_block.children)

    def assertNotParentOf(self, parent_usage_key, child_usage_key, draft=None):
        """
        Assert that the block ``parent_usage_key`` does not have ``child_usage_key`` listed
        as one of its ``.children``.

        Arguments:
            parent_usage_key: The xblock to check as a parent.
            child_usage_key: The xblock to check as a child.
            draft (optional): If omitted, verify both published and draft branches.
                If True, verify only the draft branch. If False, verify only the
                published branch.
        """
        if draft is None or not draft:
            with self.store.branch_setting(ModuleStoreEnum.Branch.published_only):
                parent_block = self.store.get_item(
                    parent_usage_key,
                )
                self.assertNotIn(child_usage_key, parent_block.children)

        if draft is None or draft:
            with self.store.branch_setting(ModuleStoreEnum.Branch.draft_preferred):
                parent_block = self.store.get_item(
                    parent_usage_key,
                )
                self.assertNotIn(child_usage_key, parent_block.children)

    def assertCoursePointsToBlock(self, block_usage_key, draft=None):
        """
        Assert that the context course for the test has ``block_usage_key`` listed
        as one of its ``.children``.

        Arguments:
            block_usage_key: The xblock to check.
            draft (optional): If omitted, verify both published and draft branches.
                If True, verify only the draft branch. If False, verify only the
                published branch.
        """
        self.assertParentOf(self.course.scope_ids.usage_id, block_usage_key, draft=draft)

    def assertCourseDoesntPointToBlock(self, block_usage_key, draft=None):
        """
        Assert that the context course for the test does not have ``block_usage_key`` listed
        as one of its ``.children``.

        Arguments:
            block_usage_key: The xblock to check.
            draft (optional): If omitted, verify both published and draft branches.
                If True, verify only the draft branch. If False, verify only the
                published branch.
        """
        self.assertNotParentOf(self.course.scope_ids.usage_id, block_usage_key, draft=draft)

    def is_detached(self, block_type):
        """
        Return True if ``block_type`` is a detached block.
        """
        return block_type in DETACHED_BLOCK_TYPES

    @ddt.data(*TESTABLE_BLOCK_TYPES)
    def test_create(self, block_type):
        self._do_create(block_type)

    # This function is split out from the test_create method so that it can be called
    # by other tests
    def _do_create(self, block_type):
        """
        Create a block of block_type (which should be a DIRECT_ONLY_CATEGORY),
        and then verify that it was created successfully, and is visible in
        both published and draft branches.
        """
        block_usage_key = self.course.id.make_usage_key(block_type, 'test_block')

        self.assertBlockDoesntExist(block_usage_key)
        self.assertCourseDoesntPointToBlock(block_usage_key)

        test_data = self.DATA_FIELDS[block_type]

        initial_field_value = test_data.initial

        with self.store.branch_setting(ModuleStoreEnum.Branch.draft_preferred):
            if self.is_detached(block_type):
                block = self.store.create_xblock(
                    self.course.runtime,
                    self.course.id,
                    block_usage_key.block_type,
                    block_id=block_usage_key.block_id
                )
                block.fields[test_data.field_name].write_to(block, initial_field_value)
                self.store.update_item(block, ModuleStoreEnum.UserID.test, allow_not_found=True)
            else:
                block = self.store.create_child(
                    user_id=ModuleStoreEnum.UserID.test,
                    parent_usage_key=self.course.scope_ids.usage_id,
                    block_type=block_type,
                    block_id=block_usage_key.block_id,
                    fields={test_data.field_name: initial_field_value},
                )

        if self.is_detached(block_type):
            self.assertCourseDoesntPointToBlock(block_usage_key)
        else:
            self.assertCoursePointsToBlock(block_usage_key)
        self.assertBlockHasContent(block_usage_key, test_data.field_name, initial_field_value)

        return block_usage_key

    @ddt.data(*TESTABLE_BLOCK_TYPES)
    def test_update(self, block_type):
        block_usage_key = self._do_create(block_type)

        with self.store.branch_setting(ModuleStoreEnum.Branch.draft_preferred):
            block = self.store.get_item(block_usage_key)

            test_data = self.DATA_FIELDS[block_type]

            updated_field_value = test_data.updated
            self.assertNotEquals(updated_field_value, block.fields[test_data.field_name].read_from(block))

            block.fields[test_data.field_name].write_to(block, updated_field_value)

            self.store.update_item(block, ModuleStoreEnum.UserID.test, allow_not_found=True)

        self.assertBlockHasContent(block_usage_key, test_data.field_name, updated_field_value)

    @ddt.data(*TESTABLE_BLOCK_TYPES)
    def test_delete(self, block_type):
        block_usage_key = self._do_create(block_type)

        with self.store.branch_setting(ModuleStoreEnum.Branch.draft_preferred):
            self.store.delete_item(block_usage_key, ModuleStoreEnum.UserID.test)

        self.assertCourseDoesntPointToBlock(block_usage_key)
        self.assertBlockDoesntExist(block_usage_key)

    @ddt.data(*itertools.product(['chapter', 'sequential'], [True, False]))
    @ddt.unpack
    def test_delete_child(self, block_type, child_published):
        block_usage_key = self.course.id.make_usage_key(block_type, 'test_block')
        child_usage_key = self.course.id.make_usage_key('html', 'test_child')

        self.assertCourseDoesntPointToBlock(block_usage_key)
        self.assertBlockDoesntExist(block_usage_key)
        self.assertBlockDoesntExist(child_usage_key)

        test_data = self.DATA_FIELDS[block_type]
        child_data = '<div>child value</div>'

        with self.store.branch_setting(ModuleStoreEnum.Branch.draft_preferred):
            self.store.create_child(
                user_id=ModuleStoreEnum.UserID.test,
                parent_usage_key=self.course.scope_ids.usage_id,
                block_type=block_type,
                block_id=block_usage_key.block_id,
                fields={test_data.field_name: test_data.initial},
            )

            self.store.create_child(
                user_id=ModuleStoreEnum.UserID.test,
                parent_usage_key=block_usage_key,
                block_type=child_usage_key.block_type,
                block_id=child_usage_key.block_id,
                fields={'data': child_data},
            )

        if child_published:
            self.store.publish(child_usage_key, ModuleStoreEnum.UserID.test)

        self.assertCoursePointsToBlock(block_usage_key)

        if child_published:
            self.assertParentOf(block_usage_key, child_usage_key)
        else:
            self.assertParentOf(block_usage_key, child_usage_key, draft=True)
            # N.B. whether the direct-only parent block points to the child in the publish branch
            # is left as undefined behavior

        self.assertBlockHasContent(block_usage_key, test_data.field_name, test_data.initial)

        if child_published:
            self.assertBlockHasContent(child_usage_key, 'data', child_data)
        else:
            self.assertBlockHasContent(child_usage_key, 'data', child_data, draft=True)
            self.assertBlockDoesntExist(child_usage_key, draft=False)

        with self.store.branch_setting(ModuleStoreEnum.Branch.draft_preferred):
            self.store.delete_item(child_usage_key, ModuleStoreEnum.UserID.test)

        self.assertCoursePointsToBlock(block_usage_key)
        self.assertNotParentOf(block_usage_key, child_usage_key)

        if child_published and self.store.get_modulestore_type(self.course.id) == ModuleStoreEnum.Type.mongo:
            # N.B. This block is being left as an orphan in old-mongo. This test will
            # fail when that is fixed. At that time, this condition should just be removed,
            # as SplitMongo and OldMongo will have the same semantics.
            self.assertBlockHasContent(child_usage_key, 'data', child_data)
        else:
            self.assertBlockDoesntExist(child_usage_key)


class TestSplitDirectOnlyCategorySemantics(DirectOnlyCategorySemantics):
    """
    Verify DIRECT_ONLY_CATEGORY semantics against the SplitMongoModulestore.
    """
    MODULESTORE = SPLIT_MODULESTORE_SETUP
    __test__ = True


class TestMongoDirectOnlyCategorySemantics(DirectOnlyCategorySemantics):
    """
    Verify DIRECT_ONLY_CATEGORY semantics against the MongoModulestore
    """
    MODULESTORE = MongoModulestoreBuilder()
    __test__ = True
