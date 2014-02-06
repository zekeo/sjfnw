from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.test.utils import override_settings
from django.utils import timezone

from sjfnw.constants import TEST_MIDDLEWARE
from sjfnw.fund import models, forms
from sjfnw.grants.models import ProjectApp
from sjfnw.tests import BaseTestCase

from datetime import timedelta
import unittest, logging
logger = logging.getLogger('sjfnw')


def set_project_dates():
  """ Sets giving project training and deadline dates """
  today = timezone.now()
  gp = models.GivingProject.objects.get(pk=1) #post
  gp.fundraising_training = today - timedelta(days=10)
  gp.fundraising_deadline = today + timedelta(days=80)
  gp.save()
  gp = models.GivingProject.objects.get(pk=2) #pre
  gp.fundraising_training = today + timedelta(days=10)
  gp.fundraising_deadline = today + timedelta(days=30)
  gp.save()

LIVE_FIXTURES = ['sjfnw/fund/fixtures/live_gp_dump.json',
                 'sjfnw/fund/fixtures/live_member_dump.json',
                 'sjfnw/fund/fixtures/live_membership_dump.json',
                 'sjfnw/fund/fixtures/live_donor_dump.json',
                 'sjfnw/fund/fixtures/live_step_dump.json']

class BaseFundTestCase(BaseTestCase):
  """ Base test case for fundraising tests

  Defines:
    Fixtures (all live dumps)
    setUp
      handles logins based on string passed in
      sets project dates
  """

  fixtures = LIVE_FIXTURES

  def setUp(self, login):
    super(BaseFundTestCase, self).setUp(login)
    if login == 'testy':
      self.logInTesty()
    elif login == 'newbie':
      self.logInNewbie()
    elif login == 'admin':
      self.logInAdmin()
    set_project_dates()

@override_settings(MIDDLEWARE_CLASSES = TEST_MIDDLEWARE)
class StepComplete(BaseFundTestCase):
  """ Tests various scenarios of test completion

  Uses step 3270, belonging to donor 2900, belonging to membership 1
  (testacct & post-training)
  """

  donor_id = 2900
  step_id = 3270
  url = reverse('sjfnw.fund.views.done_step', kwargs = {
    'donor_id': donor_id, 'step_id': step_id })

  def setUp(self, *args):
    super(StepComplete, self).setUp('testy')

  def test_valid_asked(self):
    """ Verify that an ask can be entered without any other info

    Setup:
      Complete step with asked checked and everything else blank
      (response defaults to undecided)

    Asserts:
      Successful post
      Step completed
      Step and donor marked as asked
    """

    form_data = {
        'asked': 'on',
        'response': 2,
        'promised_amount': '',
        'last_name': '',
        'notes': '',
        'next_step': '',
        'next_step_date': ''}

    step1 = models.Step.objects.get(pk=self.step_id)
    donor1 = models.Donor.objects.get(pk=self.donor_id)

    self.assertIsNone(step1.completed)
    self.assertFalse(step1.asked)
    self.assertFalse(donor1.asked)

    response = self.client.post(self.url, form_data)
    self.assertEqual(response.content, "success")

    step1 = models.Step.objects.get(pk=self.step_id)
    donor1 = models.Donor.objects.get(pk=self.donor_id)

    self.assertIsNotNone(step1.completed)
    self.assertTrue(step1.asked)
    self.assertTrue(donor1.asked)

  def test_valid_next(self):
    """ Verify success of blank form with a next step

    Setup:
      Only form info is next step and next step date

    Asserts:
      Success response
      Step completed
      New step added to DB
    """

    form_data = {'asked': '',
        'response': 2,
        'promised_amount': '',
        'last_name': '',
        'notes': '',
        'next_step': 'A BRAND NEW STEP',
        'next_step_date': '2013-01-25'}

    pre_count = models.Step.objects.count()

    response = self.client.post(self.url, form_data)
    self.assertEqual(response.content, "success")

    old_step = models.Step.objects.get(pk=self.step_id)
    self.assertIsNotNone(old_step.completed)
    self.assertEqual(pre_count + 1, models.Step.objects.count())
    self.assertEqual(1, models.Step.objects.filter(description='A BRAND NEW STEP').count())

  @unittest.skip('Incomplete')
  def test_valid_response(self): #TODO
    """ TO DO
    contact that was already asked
    add a response
    make sure step.asked stays false """
    pass

  def valid_followup(self, form_data):
    """ Not a test in itself - used by valid follow up tests

    Asserts:
      Success response
      if response is 1 (promised)
        Donor last name and/or email match form input
        Step & donor promised=form amount
      if response is 3 (declined)
        donor and step promised = 0
      if response is 2 or 3
        last name, email, promised amount are not updated
      Donor asked=True
      Step completed
      Step asked=True
    """

    pre_donor = models.Donor.objects.get(pk=self.donor_id)

    response = self.client.post(self.url, form_data)
    self.assertEqual(response.content, "success")

    promised = form_data['promised_amount']
    if promised == '5,000': #hacky workaround
      promised = 5000

    # step completion, asked update
    donor1 = models.Donor.objects.get(pk=self.donor_id)
    step1 = models.Step.objects.get(pk=self.step_id)
    self.assertTrue(donor1.asked)
    self.assertTrue(step1.asked)
    self.assertIsNotNone(step1.completed)

    # follow up info
    if form_data['response'] == 1:
      self.assertEqual(donor1.lastname, form_data['last_name'])
      self.assertEqual(donor1.email, form_data['email'])
      self.assertEqual(donor1.phone, form_data['phone'])
      self.assertEqual(donor1.promised, promised)
      self.assertEqual(step1.promised, promised)
    else:
      if form_data['response'] == 3: #declined
        self.assertEqual(donor1.promised, 0)
        self.assertEqual(step1.promised, 0)
      else:
        self.assertEqual(donor1.promised, pre_donor.promised)
        self.assertIsNone(step1.promised)
      self.assertEqual(donor1.lastname, pre_donor.lastname)
      self.assertEqual(donor1.phone, pre_donor.phone)
      self.assertEqual(donor1.email, pre_donor.email)


  def test_valid_followup1(self):
    """ Verify success of promise with amount, last name and email

    Setup:
      Form contains asked, response = promised, amount = 50,
        includes last name and email

    Asserts:
      See valid_followup
    """

    form_data = {'asked': 'on',
      'response': 1,
      'promised_amount': 50,
      'last_name': 'Sozzity',
      'phone': '',
      'email': 'blah@gmail.com',
      'notes': '',
      'next_step': 'A BRAND NEW STEP',
      'next_step_date': '2013-01-25'}

    self.valid_followup(form_data)

  def test_valid_followup2(self):
    """ Verify success of promise with amount, last name and phone number

    Setup:
      Form contains asked, response = promised, amount = 50,
        includes last name and phone number

    Asserts:
      See valid_followup
    """

    form_data = {'asked': 'on',
      'response': 1,
      'promised_amount': 50,
      'last_name': 'Sozzity',
      'phone': '206-555-5898',
      'email': '',
      'notes': '',
      'next_step': 'A BRAND NEW STEP',
      'next_step_date': '2013-01-25'}

    self.valid_followup(form_data)

  def test_valid_followup_comma(self):
    """ Verify success of promise when amount has comma in it
        (Test whether IntegerCommaField works)

    Setup:
      Form = followup2 except amount = '5,000'

    Asserts:
      See valid_followup
    """

    form_data = {'asked': 'on',
      'response': 1,
      'promised_amount': '5,000',
      'last_name': 'Sozzity',
      'phone': '206-555-5898',
      'email': '',
      'notes': '',
      'next_step': 'A BRAND NEW STEP',
      'next_step_date': '2013-01-25'}

    self.valid_followup(form_data)

  def test_valid_hiddendata1(self):

    """ promise amt + follow up + undecided
      amt & follow up info should not be saved """

    form_data = {'asked': 'on',
      'response': 2,
      'promised_amount': 50,
      'last_name': 'Sozzity',
      'phone': '206-555-5898',
      'email': '',
      'notes': '',
      'next_step': '',
      'next_step_date': ''}

    self.valid_followup(form_data)

  def test_valid_hiddendata2(self):

    """ declined + promise amt + follow up
      amt & follow up info should not be saved
      step.promised & donor.promised = 0 """

    form_data = {'asked': 'on',
      'response': 3,
      'promised_amount': 50,
      'last_name': 'Sozzity',
      'phone': '206-555-5898',
      'email': '',
      'notes': '',
      'next_step': '',
      'next_step_date': ''}

    self.valid_followup(form_data)

  def test_valid_hiddendata3(self):

    """ promise amt + follow up + undecided
      allow without followup
      don't save promise on donor or step """

    form_data = {'asked': 'on',
      'response': 2,
      'promised_amount': 50,
      'last_name': '',
      'phone': '',
      'email': '',
      'notes': '',
      'next_step': '',
      'next_step_date': ''}

    self.valid_followup(form_data)

  def test_invalid_promise(self):
    """ Verify that additional info is required when a promise is entered

    Setup:
      Complete a step with response promised, but no amount, phone or email

    Asserts:
      Form template used (not successful)
      Form errors on promised_amount, last_name, phone
      Step and donor not modified
    """

    form_data = {
        'asked': 'on',
        'response': 1,
        'promised_amount': '',
        'last_name': '',
        'notes': '',
        'next_step': '',
        'next_step_date': ''}

    step1 = models.Step.objects.get(pk=self.step_id)
    donor1 = models.Donor.objects.get(pk=self.donor_id)

    self.assertIsNone(step1.completed)
    self.assertFalse(step1.asked)
    self.assertFalse(donor1.asked)

    response = self.client.post(self.url, form_data)

    self.assertTemplateUsed(response, 'fund/done_step.html')
    self.assertFormError(response, 'form', 'promised_amount', "Enter an amount.")
    self.assertFormError(response, 'form', 'last_name', "Enter a last name.")
    self.assertFormError(response, 'form', 'phone', "Enter a phone number or email.")

    step1 = models.Step.objects.get(pk=self.step_id)
    donor1 = models.Donor.objects.get(pk=self.donor_id)

    self.assertIsNone(step1.completed)
    self.assertFalse(step1.asked)
    self.assertFalse(donor1.asked)

  def test_invalid_next(self):

    """ missing date
        missing desc """

    form_data = {'asked': '',
        'response': 2,
        'promised_amount': '',
        'last_name': '',
        'notes': '',
        'next_step': 'A step description!',
        'next_step_date': ''}

    response = self.client.post(self.url, form_data)

    self.assertTemplateUsed(response, 'fund/done_step.html')
    self.assertFormError(response, 'form', 'next_step_date', "Enter a date in mm/dd/yyyy format.")

    step1 = models.Step.objects.get(pk=self.step_id)
    self.assertIsNone(step1.completed)

    form_data = {'asked': '',
        'response': 2,
        'promised_amount': '',
        'last_name': '',
        'notes': '',
        'next_step': '',
        'next_step_date': '2013-01-25'}

    response = self.client.post(self.url, form_data)
    self.assertTemplateUsed(response, 'fund/done_step.html')
    self.assertFormError(response, 'form', 'next_step', "Enter a description.")

    step1 = models.Step.objects.get(pk=self.step_id)
    self.assertIsNone(step1.completed)

@override_settings(MIDDLEWARE_CLASSES = TEST_MIDDLEWARE)
class Home(BaseFundTestCase):

  url = reverse('sjfnw.fund.views.home')

  def setUp(self):
    super(Home, self).setUp('newbie')

  def test_new(self):
    """ Verify that add mult form is shown to new memberships

    Setup:
      Member has no prior contacts
      Login to membership in pre-training with 0 contacts
      Login to membership in post-training with 0 contacts

    Asserts:
      Both use add_mult_flex.html
      'likelihood' is in in the form for Post only
    """

    membership = models.Membership.objects.get(pk=2) # pre

    response = self.client.get(self.url, follow=True)
    self.assertTemplateUsed(response, 'fund/add_mult_flex.html')
    self.assertEqual(response.context['request'].membership, membership)
    self.assertNotContains(response, 'likelihood')

    member = membership.member
    member.current = 6 # post
    member.save()

    response = self.client.get(self.url, follow=True)

    membership = models.Membership.objects.get(pk=6)
    self.assertTemplateUsed(response, 'fund/add_mult_flex.html')
    self.assertEqual(response.context['request'].membership, membership)
    self.assertContains(response, 'likelihood')

  def test_contacts_without_est(self):

    """ 2 contacts w/o est
        logs into post training, gets estimates form
        logs into pre, does not """

    membership = models.Membership.objects.get(pk=2) #pre

    contact1 = models.Donor(firstname='Anna', membership=membership)
    contact1.save()
    contact2 = models.Donor(firstname='Banana', membership=membership)
    contact2.save()

    response = self.client.get(self.url)
    self.assertEqual(response.context['request'].membership, membership)
    self.assertTemplateNotUsed('fund/add_estimates.html')

    member = membership.member
    member.current = 6 # post
    member.save()

    membership = models.Membership.objects.get(pk=6)

    contact1.membership = membership
    contact1.save()
    contact2.membership = membership
    contact2.save()

    response = self.client.get(self.url)
    self.assertEqual(response.context['request'].membership, membership)
    self.assertTemplateUsed('fund/add_estimates.html')

  def test_estimates(self):

    """ 2 contacts w/est
        logs into post training, gets reg list """

    membership = models.Membership.objects.get(pk=2)

    contact = models.Donor(firstname='Anna', membership=membership, amount=0, likelihood=0)
    contact.save()
    contact = models.Donor(firstname='Banana', membership=membership, amount=567, likelihood=34)
    contact.save()

    response = self.client.get(self.url)
    self.assertTemplateNotUsed('fund/add_estimates.html')

  def test_contacts_list(self):
    """ Verify correct display of a long contact list with steps, history

    Setup:
      Use membership 96 (test & gp 10) which has 29 contacts

    Asserts:
      ASSERTIONS
    """

    self.logInTesty()
    member = models.Member.objects.get(pk=1)
    member.current = 96
    member.save()

    response = self.client.get(self.url)
    print(response.context['donor_list'])

  @unittest.skip('Incomplete')
  def test_gift_notification(self):
    pass

    """ add a gift to donor
        test that notif shows up on next load
        test that notif is gone on next load """


@override_settings(MIDDLEWARE_CLASSES = TEST_MIDDLEWARE)
class Grants(BaseFundTestCase):
  """ Grants listing page """

  fixtures = LIVE_FIXTURES + ['sjfnw/grants/fixtures/orgs.json',
                              'sjfnw/grants/fixtures/grant_cycles.json',
                              'sjfnw/grants/fixtures/apps.json'
                              'sjfnw/grants/fixtures/project_apps.json']
  url = reverse('sjfnw.fund.views.grant_list')

  def setUp(self):
    super(Grants, self).setUp('testy')
    
  def test_grants_display(self):
    """ Verify that assigned grants are shown on grants page
    
    Setup:
      Use GP 19, create membership for testy
    
    Asserts:
      Assert that an identifying string for each application appears on page
    """
    
    ship = models.Membership(giving_project_id=19, member_id=1)
    ship.save()
    member = models.Member.objects.get(pk=1)
    member.current = ship.pk
    member.save()

    response = self.client.get(self.url)

    papps = ProjectApp.objects.filter(giving_project_id=19).select_related(
        'application', 'application__organization')
    self.assertNotEqual(papps, [])
    for papp in papps:
      self.assertContains(response, str(papp.application.organization))


@override_settings(MIDDLEWARE_CLASSES = TEST_MIDDLEWARE)
class CopyContacts(BaseFundTestCase):
  """ Test copy_contacts view """

  fixtures = LIVE_FIXTURES
  url = reverse('sjfnw.fund.views.home')
  template = 'fund/copy_contacts.html'

  def setUp(self):
    super(CopyContacts, self).setUp('')

  """ want to test scenarios: 
        cs from different gps
        no contacts (make sure this page isn't triggered)
        duplicates
          matching on last, phone or email
          both blank
          newest blank, older has info
          both have info
  """
  
  def test_display_no_duplicates(self):
    """ Verify that form display is correct when user has non-dup contacts
    
    Setup:
      Borrow a membership that has 13 non-dup contacts
      Assign it to newbie, set active
      Go to home page
      
    Asserts:

    """
    member = models.Member.objects.get(pk=4)
    member.current = 132
    member.save()
    membership = models.Membership.objects.get(pk=132)
    membership.member = member
    membership.save()

    self.logInNewbie()

    response = self.client.get(self.url)
    
    print(response.context)
    initial = response.context['formset'].management_form['form-INITIAL_FORMS']
    self.assertEqual(initial, str(membership.donor_set.count()))


  def test_display_duplicates(self):
    """ Verify proper merging of display (does not test hidden fields)
    
    Setup:
      Borrow membership 132 which has 13 non-dup contacts
      Add duplicates in all 3 ways (last, phone, email)
      
    Asserts:
      Only 13 initial forms are shown
      """
    member = models.Member.objects.get(pk=4)
    member.current = 132
    member.save()
    membership = models.Membership.objects.get(pk=132)
    membership.member = member
    membership.save()
    unique_donors = membership.donor_set.count()

    copy = models.Donor(membership_id=132, firstname="Gordon", lastname="Gray")
    copy.save()
    copy = models.Donor(membership_id=132, firstname="Emily",
                        email="Emilyagray@gmail.com")
    copy.save()
    copy = models.Donor(membership_id=132, firstname="Judy", phone="206-785-9807")
    copy.save()

    self.logInNewbie()

    response = self.client.get(self.url)
    
    print(response.context)
    initial = response.context['formset'].management_form['form-INITIAL_FORMS']
    self.assertEqual(initial, str(unique_donors))
  
  @unittest.skip('Incomplete')
  def test_skip(self):
    """ Verify that skip works """
    pass

  @unittest.skip('Incomplete')
  def test_copy_no_duplicates(self):
    """ Verify that selected contacts are copied """
    pass

  @unittest.skip('Incomplete')
  def test_copy_merging(self):
    """ Verify that duplicate contacts are properly merged """
    pass
  
  
  

""" TEST IDEAS
      gift notification & email
      update story (deferred) """

