"""
Adds crowdsourced hinting functionality to lon-capa numerical response problems.

Currently experimental - not for instructor use, yet.
"""

import logging
import json
import random
import copy

from pkg_resources import resource_string

from lxml import etree

from xmodule.x_module import XModule, STUDENT_VIEW
from xmodule.raw_module import RawDescriptor
from xblock.fields import Scope, String, Integer, Boolean, Dict, List

from capa.responsetypes import FormulaResponse

from django.utils.html import escape

log = logging.getLogger(__name__)


class CrowdsourceHinterFields(object):
    """Defines fields for the crowdsource hinter module."""
    has_children = True

    moderate = String(help='String "True"/"False" - activates moderation', scope=Scope.content,
                      default='False')
    debug = String(help='String "True"/"False" - allows multiple voting', scope=Scope.content,
                   default='False')
    # Usage: hints[answer] = {str(pk): [hint_text, #votes]}
    # hints is a dictionary that takes answer keys.
    # Each value is itself a dictionary, accepting hint_pk strings as keys,
    # and returning [hint text, #votes] pairs as values
    hints = Dict(help='A dictionary containing all the active hints.', scope=Scope.content, default={})
    mod_queue = Dict(help='A dictionary containing hints still awaiting approval', scope=Scope.content,
                     default={})
    hint_pk = Integer(help='Used to index hints.', scope=Scope.content, default=0)

    # A list of previous hints that a student viewed.
    # Of the form [answer, [hint_pk_1, ...]] for each problem.
    # Sorry about the variable name - I know it's confusing.
    previous_answers = List(help='A list of hints viewed.', scope=Scope.user_state, default=[])

    # user_submissions actually contains a list of previous answers submitted.
    # (Originally, preivous_answers did this job, hence the name confusion.)
    user_submissions = List(help='A list of previous submissions', scope=Scope.user_state, default=[])
    user_voted = Boolean(help='Specifies if the user has voted on this problem or not.',
                         scope=Scope.user_state, default=False)


class CrowdsourceHinterModule(CrowdsourceHinterFields, XModule):
    """
    An Xmodule that makes crowdsourced hints.
    Currently, only works on capa problems with exactly one numerical response,
    and no other parts.

    Example usage:
    <crowdsource_hinter>
        <problem blah blah />
    </crowdsource_hinter>

    XML attributes:
    -moderate="True" will not display hints until staff approve them in the hint manager.
    -debug="True" will let users vote as often as they want.
    """
    icon_class = 'crowdsource_hinter'
    css = {'scss': [resource_string(__name__, 'css/crowdsource_hinter/display.scss')]}
    js = {'coffee': [resource_string(__name__, 'js/src/crowdsource_hinter/display.coffee')],
          'js': []}
    js_module_name = "Hinter"

    def __init__(self, *args, **kwargs):
        super(CrowdsourceHinterModule, self).__init__(*args, **kwargs)
        # We need to know whether we are working with a FormulaResponse problem.
        try:
            responder = self.get_display_items()[0].lcp.responders.values()[0]
        except (IndexError, AttributeError):
            log.exception('Unable to find a capa problem child.')
            return

        self.is_formula = isinstance(self, FormulaResponse)
        if self.is_formula:
            self.answer_to_str = self.formula_answer_to_str
        else:
            self.answer_to_str = self.numerical_answer_to_str
        # compare_answer is expected to return whether its two inputs are close enough
        # to be equal, or raise a StudentInputError if one of the inputs is malformatted.
        if hasattr(responder, 'compare_answer') and hasattr(responder, 'validate_answer'):
            self.compare_answer = responder.compare_answer
            self.validate_answer = responder.validate_answer
        else:
            # This response type is not supported!
            log.exception('Response type not supported for hinting: ' + str(responder))

    def get_html(self):
        """
        Puts a wrapper around the problem html.  This wrapper includes ajax urls of the
        hinter and of the problem.
        - Dependent on lon-capa problem.
        """
        if self.debug == 'True':
            # Reset the user vote, for debugging only!
            self.user_voted = False
        if self.hints == {}:
            # Force self.hints to be written into the database.  (When an xmodule is initialized,
            # fields are not added to the db until explicitly changed at least once.)
            self.hints = {}

        try:
            child = self.get_display_items()[0]
            out = child.render(STUDENT_VIEW).content
            # The event listener uses the ajax url to find the child.
            child_id = child.id
        except IndexError:
            out = u"Error in loading crowdsourced hinter - can't find child problem."
            child_id = ''

        # Wrap the module in a <section>.  This lets us pass data attributes to the javascript.
        out += u'<section class="crowdsource-wrapper" data-url="{ajax_url}" data-child-id="{child_id}"> </section>'.format(
            ajax_url=self.runtime.ajax_url,
            child_id=child_id
        )

        return out

    def numerical_answer_to_str(self, answer):
        """
        Converts capa numerical answer format to a string representation
        of the answer.
        -Lon-capa dependent.
        -Assumes that the problem only has one part.
        """
        return str(answer.values()[0])

    def formula_answer_to_str(self, answer):
        """
        Converts capa formula answer into a string.
        -Lon-capa dependent.
        -Assumes that the problem only has one part.
        """
        return str(answer.values()[0])

    def get_matching_answers(self, answer):
        """
        Look in self.hints, and find all answer keys that are "equal with tolerance"
        to the input answer.
        """
        return [key for key in self.hints if self.compare_answer(key, answer)]

    def handle_ajax(self, dispatch, data):
        """
        This is the landing method for AJAX calls.
        """
        if dispatch == 'get_hint':
            out = self.get_hint(data)
        elif dispatch == 'get_feedback':
            out = self.get_feedback(data)
        elif dispatch == 'vote':
            out = self.tally_vote(data)
        elif dispatch == 'submit_hint':
            out = self.submit_hint(data)
        else:
            return json.dumps({'contents': 'Error - invalid operation.'})

        if out is None:
            out = {'op': 'empty'}
        elif 'error' in out:
            # Error in processing.
            out.update({'op': 'error'})
        else:
            out.update({'op': dispatch})
        return json.dumps({'contents': self.runtime.render_template('hinter_display.html', out)})

    def get_hint(self, data):
        """
        The student got the incorrect answer found in data.  Give him a hint.

        Called by hinter javascript after a problem is graded as incorrect.
        Args:
        `data` -- must be interpretable by answer_to_str.
        Output keys:
            - 'hints' is a list of hint strings to show to the user.
            - 'answer' is the parsed answer that was submitted.
        Will record the user's wrong answer in user_submissions, and the hints shown
        in previous_answers.
        """
        # First, validate our inputs.
        try:
            answer = self.answer_to_str(data)
        except (ValueError, AttributeError):
            # Sometimes, we get an answer that's just not parsable.  Do nothing.
            log.exception('Answer not parsable: ' + str(data))
            return
        if not self.validate_answer(answer):
            # Answer is not in the right form.
            log.exception('Answer not valid: ' + str(answer))
            return
        if answer not in self.user_submissions:
            self.user_submissions += [answer]

        # For all answers similar enough to our own, accumulate all hints together.
        # Also track the original answer of each hint.
        matching_answers = self.get_matching_answers(answer)
        matching_hints = {}
        for matching_answer in matching_answers:
            temp_dict = copy.deepcopy(self.hints[matching_answer])
            for key, value in temp_dict.items():
                # Each value now has hint, votes, matching_answer.
                temp_dict[key] = value + [matching_answer]
            matching_hints.update(temp_dict)
        # matching_hints now maps pk's to lists of [hint, votes, matching_answer]

        # Finally, randomly choose a subset of matching_hints to actually show.
        if not matching_hints:
            # No hints to give.  Return.
            return
        # Get the top hint, plus two random hints.
        n_hints = len(matching_hints)
        hints = []
        # max(dict) returns the maximum key in dict.
        # The key function takes each pk, and returns the number of votes for the
        # hint with that pk.
        best_hint_index = max(matching_hints, key=lambda pk: matching_hints[pk][1])
        hints.append(matching_hints[best_hint_index][0])
        best_hint_answer = matching_hints[best_hint_index][2]
        # The brackets surrounding the index are for backwards compatability purposes.
        # (It used to be that each answer was paired with multiple hints in a list.)
        self.previous_answers += [[best_hint_answer, [best_hint_index]]]
        for _ in xrange(min(2, n_hints - 1)):
            # Keep making random hints until we hit a target, or run out.
            while True:
                # random.choice randomly chooses an element from its input list.
                # (We then unpack the item, in this case data for a hint.)
                (hint_index, (rand_hint, _, hint_answer)) =\
                    random.choice(matching_hints.items())
                if rand_hint not in hints:
                    break
            hints.append(rand_hint)
            self.previous_answers += [[hint_answer, [hint_index]]]
        return {'hints': hints,
                'answer': answer}

    def get_feedback(self, data):
        """
        The student got it correct.  Ask him to vote on hints, or submit a hint.

        Args:
        `data` -- not actually used.  (It is assumed that the answer is correct.)
        Output keys:
            - 'answer_to_hints': a nested dictionary.
              answer_to_hints[answer][hint_pk] returns the text of the hint.
            - 'user_submissions': the same thing as self.user_submissions.  A list of
              the answers that the user previously submitted.
        """
        # The student got it right.
        # Did he submit at least one wrong answer?
        if len(self.user_submissions) == 0:
            # No.  Nothing to do here.
            return
        # Make a hint-voting interface for each wrong answer.  The student will only
        # be allowed to make one vote / submission, but he can choose which wrong answer
        # he wants to look at.
        answer_to_hints = {}    # answer_to_hints[answer text][hint pk] -> hint text

        # Go through each previous answer, and populate index_to_hints and index_to_answer.
        for i in xrange(len(self.previous_answers)):
            answer, hints_offered = self.previous_answers[i]
            if answer not in answer_to_hints:
                answer_to_hints[answer] = {}
            if answer in self.hints:
                # Go through each hint, and add to index_to_hints
                for hint_id in hints_offered:
                    if (hint_id is not None) and (hint_id not in answer_to_hints[answer]):
                        try:
                            answer_to_hints[answer][hint_id] = self.hints[answer][str(hint_id)][0]
                        except KeyError:
                            # Sometimes, the hint that a user saw will have been deleted by the instructor.
                            continue
        return {'answer_to_hints': answer_to_hints,
                'user_submissions': self.user_submissions}

    def tally_vote(self, data):
        """
        Tally a user's vote on his favorite hint.

        Args:
        `data` -- expected to have the following keys:
            'answer': text of answer we're voting on
            'hint': hint_pk
            'pk_list': A list of [answer, pk] pairs, each of which representing a hint.
                       We will return a list of how many votes each hint in the list has so far.
                       It's up to the browser to specify which hints to return vote counts for.

        Returns key 'hint_and_votes', a list of (hint_text, #votes) pairs.
        """
        if self.user_voted:
            return {'error': 'Sorry, but you have already voted!'}
        ans = data['answer']
        if not self.validate_answer(ans):
            # Uh oh.  Invalid answer.
            log.exception('Failure in hinter tally_vote: Unable to parse answer: {ans}'.format(ans=ans))
            return {'error': 'Failure in voting!'}
        hint_pk = str(data['hint'])
        # We use temp_dict because we need to do a direct write for the database to update.
        temp_dict = self.hints
        try:
            temp_dict[ans][hint_pk][1] += 1
        except KeyError:
            log.exception('''Failure in hinter tally_vote: User voted for non-existant hint:
                             Answer={ans} pk={hint_pk}'''.format(ans=ans, hint_pk=hint_pk))
            return {'error': 'Failure in voting!'}
        self.hints = temp_dict
        # Don't let the user vote again!
        self.user_voted = True

        # Return a list of how many votes each hint got.
        pk_list = json.loads(data['pk_list'])
        hint_and_votes = []
        for answer, vote_pk in pk_list:
            if not self.validate_answer(answer):
                log.exception('In hinter tally_vote, couldn\'t parse {ans}'.format(ans=answer))
                continue
            try:
                hint_and_votes.append(temp_dict[answer][str(vote_pk)])
            except KeyError:
                log.exception('In hinter tally_vote, couldn\'t find: {ans}, {vote_pk}'.format(
                              ans=answer, vote_pk=str(vote_pk)))

        hint_and_votes.sort(key=lambda pair: pair[1], reverse=True)
        # Reset self.previous_answers and user_submissions.
        self.previous_answers = []
        self.user_submissions = []
        return {'hint_and_votes': hint_and_votes}

    def submit_hint(self, data):
        """
        Take a hint submission and add it to the database.

        Args:
        `data` -- expected to have the following keys:
            'answer': text of answer
            'hint': text of the new hint that the user is adding
        Returns a thank-you message.
        """
        # Do html escaping.  Perhaps in the future do profanity filtering, etc. as well.
        hint = escape(data['hint'])
        answer = data['answer']
        if not self.validate_answer(answer):
            log.exception('Failure in hinter submit_hint: Unable to parse answer: {ans}'.format(
                          ans=answer))
            return {'error': 'Could not submit answer'}
        # Only allow a student to vote or submit a hint once.
        if self.user_voted:
            return {'message': 'Sorry, but you have already voted!'}
        # Add the new hint to self.hints or self.mod_queue.  (Awkward because a direct write
        # is necessary.)
        if self.moderate == 'True':
            temp_dict = self.mod_queue
        else:
            temp_dict = self.hints
        if answer in temp_dict:
            temp_dict[answer][str(self.hint_pk)] = [hint, 1]     # With one vote (the user himself).
        else:
            temp_dict[answer] = {str(self.hint_pk): [hint, 1]}
        self.hint_pk += 1
        if self.moderate == 'True':
            self.mod_queue = temp_dict
        else:
            self.hints = temp_dict
        # Mark the user has having voted; reset previous_answers
        self.user_voted = True
        self.previous_answers = []
        self.user_submissions = []
        return {'message': 'Thank you for your hint!'}


class CrowdsourceHinterDescriptor(CrowdsourceHinterFields, RawDescriptor):
    module_class = CrowdsourceHinterModule
    stores_state = True

    @classmethod
    def definition_from_xml(cls, xml_object, system):
        children = []
        for child in xml_object:
            try:
                child_block = system.process_xml(etree.tostring(child, encoding='unicode'))
                children.append(child_block.scope_ids.usage_id)
            except Exception as e:
                log.exception("Unable to load child when parsing CrowdsourceHinter. Continuing...")
                if system.error_tracker is not None:
                    system.error_tracker(u"ERROR: {0}".format(e))
                continue
        return {}, children

    def definition_to_xml(self, resource_fs):
        xml_object = etree.Element('crowdsource_hinter')
        for child in self.get_children():
            self.runtime.add_block_as_child_node(child, xml_object)
        return xml_object
