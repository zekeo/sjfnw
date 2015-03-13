from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.humanize.templatetags.humanize import intcomma
from django.core.urlresolvers import reverse
from django.forms.formsets import formset_factory
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect
from django.utils import timezone

from google.appengine.ext import deferred, ereporter

from sjfnw import constants as c
from sjfnw.grants.models import Organization, ProjectApp

from sjfnw.fund.decorators import approved_membership
from sjfnw.fund import forms, modelforms, models

import datetime, logging, os, json

if not settings.DEBUG:
  ereporter.register_logger()

logger = logging.getLogger('sjfnw')

#-----------------------------------------------------------------------------
# MAIN VIEWS
#-----------------------------------------------------------------------------

@login_required(login_url='/fund/login/')
@approved_membership()
def home(request):
  """ Handles display of the home/personal page

  Redirects:
    no contacts -> copy_contacts or add_mult
    contacts without estimates + post-training + no url params -> add_estimates

  Handles display of
    Top blocks
    Charts of personal progress
    List of donors, with details and associated steps
    Url param can trigger display of a form on a specific donor/step
  """

  membership = request.membership

  # check if there's a survey to fill out
  surveys = (models.GPSurvey.objects
      .filter(giving_project=membership.giving_project,
              date__lte=timezone.now())
      .exclude(id__in=json.loads(membership.completed_surveys))
      .order_by('date'))

  if surveys:
    logger.info('Needs to fill out survey; redirecting')
    return redirect(reverse('sjfnw.fund.views.project_survey', kwargs={
      'gp_survey_id': surveys[0].pk
    }))

  # check if they have contacts
  donors = membership.donor_set.all()
  if not donors:
    if not membership.copied_contacts:
      all_donors = models.Donor.objects.filter(membership__member=membership.member)
      if all_donors:
        logger.info('Eligible to copy contacts; redirecting')
        return redirect(copy_contacts)
    return redirect(add_mult)

  # check whether to redirect to add estimates
  if (membership.giving_project.require_estimates() and
      donors.filter(amount__isnull=True)):
    return redirect(add_estimates)

  # from here we know we're not redirecting

  # top content
  _, news, grants = _get_block_content(membership, get_steps=False)
  header = membership.giving_project.title

  donor_data, progress = _compile_membership_progress(donors)

  notif = membership.notifications
  # on live, only show a notification once
  if notif and not settings.DEBUG:
    logger.info('Displaying notification to ' + unicode(membership) + ': ' + notif)
    membership.notifications = ''
    membership.save(skip=True)

  # get all steps
  steps = models.Step.objects.filter(donor__membership=membership).order_by('date')

  # split steps into complete/not, attach to donors
  donor_list, upcoming_steps = _compile_steps(donor_data, list(steps))

  # suggested steps for step forms
  suggested = membership.giving_project.get_suggested_steps()
  sugg_word = membership.giving_project.get_first_word()

  # parse url params
  step = request.GET.get('step')
  donor = request.GET.get('donor')
  form_type = request.GET.get('t')
  load_form = request.GET.get('load')
  if step and donor and form_type:
    load = '/fund/'+donor+'/'+step
    if form_type == "complete":
      load += '/done'
    loadto = donor + '-nextstep'
  elif load_form == 'stepmult':
    load = '/fund/stepmult'
    loadto = 'addmult'
  else: # no form specified
    load = ''
    loadto = ''

  return render(request, 'fund/home.html', {
    '1active': 'true', 'header': header, 'news': news, 'grants': grants,
    'steps': upcoming_steps, 'donor_list': donor_list, 'progress': progress,
    'notif': notif, 'suggested': suggested, 'load': load, 'loadto': loadto
  })

def _compile_membership_progress(donors):
  # collect & organize contact data
  progress = {'contacts': len(donors), 'estimated': 0, 'talked': 0,
          'asked': 0, 'promised': 0, 'received': 0}
  donor_data = {}

  if not donors:
    logger.error('No contacts but no redirect to add_mult')
    progress['contactsremaining'] = 0
    return donor_data, progress

  empty_date = datetime.date(2500, 1, 1)
  logger.info(donors)
  for donor in donors:
    donor_data[donor.pk] = {'donor': donor, 'complete_steps': [],
                            'next_step': False, 'next_date': empty_date,
                            'overdue': False, 'summary': ''}
    progress['estimated'] += donor.estimated()
    if donor.asked:
      progress['asked'] += 1
      donor_data[donor.pk]['next_date'] = datetime.date(2600, 1, 1)
      donor_data[donor.pk]['summary'] = 'Asked. '
    elif donor.talked:
      progress['talked'] += 1
    if donor.received() > 0:
      progress['received'] += donor.received()
      donor_data[donor.pk]['next_date'] = datetime.date(2800, 1, 1)
      donor_data[donor.pk]['summary'] += ' $%s received by SJF.' % intcomma(donor.received())
    elif donor.promised:
      progress['promised'] += donor.promised
      donor_data[donor.pk]['next_date'] = datetime.date(2700, 1, 1)
      donor_data[donor.pk]['summary'] += ' Promised $%s.' % intcomma(donor.promised)
    elif donor.asked:
      if donor.promised == 0:
        donor_data[donor.pk]['summary'] += ' Declined to donate.'
      else:
        donor_data[donor.pk]['summary'] += ' Awaiting response.'

  progress = _compile_membership_chart_data(progress)

  return donor_data, progress

def _compile_membership_chart_data(progress):
  # progress chart calculations
  if progress['contacts'] > 0:
    progress['bar'] = 100 * progress['asked']/progress['contacts']
    progress['contactsremaining'] = progress['contacts'] - progress['talked'] - progress['asked']
    progress['togo'] = progress['estimated'] - progress['promised'] - progress['received']
    progress['header'] = '$' + intcomma(progress['estimated']) + ' fundraising goal'
    if progress['togo'] < 0:
      # met or exceeded goal - override goal header with total fundraised
      progress['togo'] = 0
      progress['header'] = ('$' + intcomma(progress['promised'] + progress['received']) +
                        ' raised')
  return progress

def _compile_steps(donor_data, steps):
  if not steps:
    return donor_data.values(), []

  upcoming = []
  ctz = timezone.get_current_timezone()
  today = ctz.normalize(timezone.now()).date()
  for step in steps:
    if step.completed:
      donor_data[step.donor_id]['complete_steps'].append(step)
    else:
      upcoming.append(step)
      donor_data[step.donor_id]['next_step'] = step
      donor_data[step.donor_id]['next_date'] = step.date
      if step.date < today:
        donor_data[step.donor_id]['overdue'] = True
  upcoming.sort(key=lambda step: step.date)
  donor_list = donor_data.values() # convert outer dict to list and sort it
  donor_list.sort(key=lambda donor: donor['next_date'])

  return donor_list, upcoming

@login_required(login_url='/fund/login/')
@approved_membership()
def project_page(request):

  membership = request.membership
  project = membership.giving_project

  # blocks
  steps, news, grants = _get_block_content(membership)

  header = project.title

  # project metrics/progress
  progress = {'contacts': 0, 'talked': 0, 'asked': 0, 'promised': 0, 'received': 0}
  donors = list(models.Donor.objects.filter(membership__giving_project=project))
  progress['contacts'] = len(donors)
  for donor in donors:
    donor.summary = []
    if donor.asked:
      progress['asked'] += 1
    elif donor.talked:
      progress['talked'] += 1
    if donor.received() > 0:
      progress['received'] += donor.received()
    elif donor.promised:
      progress['promised'] += donor.promised

  progress['contactsremaining'] = progress['contacts'] - progress['talked'] -  progress['asked']
  progress['togo'] = project.fund_goal - progress['promised'] -  progress['received']
  if progress['togo'] < 0:
    progress['togo'] = 0

  # project resources
  resources = (models.ProjectResource.objects.filter(giving_project=project)
                                             .select_related('resource')
                                             .order_by('session'))

  return render(request, 'fund/project.html', {
    '2active': 'true', 'header': header, 'news': news, 'grants': grants,
    'steps': steps, 'project_progress': progress, 'resources': resources
  })


@login_required(login_url='/fund/login/')
@approved_membership()
def grant_list(request):

  membership = request.membership
  project = membership.giving_project

  # blocks
  steps, news, grants = _get_block_content(membership)

  # base
  header = project.title

  return render(request, 'fund/grants.html', {
    '3active': 'true', 'header': header, 'news': news, 'steps': steps,
    'membership': membership, 'grants': grants
  })

#-----------------------------------------------------------------------------
# LOGIN & REGISTRATION
#-----------------------------------------------------------------------------

def fund_login(request):
  error_msg = ''
  if request.method == 'POST':
    form = forms.LoginForm(request.POST)
    if form.is_valid():
      username = request.POST['email'].lower()
      password = request.POST['password']
      user = authenticate(username=username, password=password)
      if user:
        if user.is_active:
          login(request, user)
          return redirect(home)
        else:
          error_msg = 'Your account is not active.  Contact an administrator.'
          logger.warning("Inactive account tried to log in. Username: "+username)
      else:
        error_msg = "Your login and password didn't match."
      logger.info(error_msg)
  else:
    form = forms.LoginForm()
  return render(request, 'fund/login.html', {'form': form, 'error_msg': error_msg})


def fund_register(request):
  error_msg = ''
  if request.method == 'POST':
    register = forms.RegistrationForm(request.POST)
    if register.is_valid():

      username_email = request.POST['email'].lower()
      password = request.POST['password']
      first_name = request.POST['first_name']
      last_name = request.POST['last_name']

      user, member, error_msg = _create_user(username_email, password,
                                             first_name, last_name)
      if not error_msg:
        # if they specified a GP, create Membership
        membership = None
        if request.POST['giving_project']:
          giv = models.GivingProject.objects.get(pk=request.POST['giving_project'])
          notif = ('<table><tr><td>Welcome to Project Central!<br>'
              'I\'m Odo, your Online Donor Organizing assistant. I\'ll be here to '
              'guide you through the fundraising process and cheer you on.</td>'
              '<td><img src="/static/images/odo1.png" height=88 width=54 alt="Odo waving">'
              '</td></tr></table>')
          membership, _ = _create_membership(member, giv, notif=notif)
          logger.info('Registration - membership in %s created, welcome message set', unicode(giv))

        # try to log in
        user = authenticate(username=username_email, password=password)
        if user:
          if user.is_active:
            # success! log in and redirect
            login(request, user)
            if not membership:
              return redirect(manage_account)
            if membership.approved:
              return redirect(home)
            return render(request, 'fund/registered.html', {
              'member': member, 'proj': giv
            })
          else: # not active
            error_msg = 'Your account is not active. Please contact a site admin for assistance.'
            logger.error('Inactive right after registering. Email: ' + username_email)
        else: # email & pw didn't match
          error_msg = ('There was a problem with your registration.  Please '
              '<a href="/fund/support# contact">contact a site admin</a> for assistance.')
          logger.error('Password didn\'t match right after registering. Email: %s',
              username_email)

  else: # GET
    register = forms.RegistrationForm()

  return render(request, 'fund/register.html', {
    'form': register, 'error_msg': error_msg
  })


@login_required(login_url='/fund/login/')
def registered(request):
  """ Sets up a member after registration # TODO could this be a func instead of view?

  If they have no memberships, send them to projects page

  Checks membership for pre-approval status
  """

  if request.membership_status == c.NO_MEMBER:
    return redirect(not_member)
  elif request.membership_status == c.NO_MEMBERSHIP:
    return redirect(manage_account)
  else:
    member = models.Member.objects.get(email=request.user.username)

  # if they came here from manage_aaccount, 'sh' should be a url param
  # if from register, member.current should be set
  ship_id = request.GET.get('sh') or member.current
  try:
    ship = models.Membership.objects.get(pk=ship_id, member=member)

  except models.Membership.DoesNotExist: # should not happen
    logger.error('Membership does not exist right at /registered ' + request.user.username)
    return redirect(home)
  if ship.approved == True: # another precaution
    logger.warning('Membership approved before check at /registered ' + request.user.username)
    return redirect(home)

  # check if they're on the pre-approved list
  gp = ship.giving_project
  if gp.is_pre_approved(member.email):
    ship.approved = True
    ship.save(skip=True)
    member.current = ship_id
    member.save()
    logger.info('Pre-approval succeeded')
    return redirect(home)

  return render(request, 'fund/registered.html', {
    'member': member, 'proj': gp
  })



#-----------------------------------------------------------------------------
# MEMBERSHIP MANAGEMENT
#-----------------------------------------------------------------------------

@login_required(login_url='/fund/login/')
def manage_account(request):

  if request.membership_status == c.NO_MEMBER:
    return redirect(not_member)
  else:
    member = models.Member.objects.get(email=request.user.username)

  ships = member.membership_set.all()

  error_msg = ''
  if request.method == 'POST':
    form = forms.AddProjectForm(request.POST)
    if form.is_valid():
      logger.debug('Valid add project')
      gp = request.POST['giving_project']
      giv = models.GivingProject.objects.get(pk=gp)
      membership, error_msg = _create_membership(member, giv)
      if membership:
        if membership.approved:
          return redirect(home)
        return render(request, 'fund/registered.html', {
          'member': member, 'proj': giv
        })
  else: # GET
    form = forms.AddProjectForm()

  return render(request, 'fund/account_projects.html', {
    'member': member, 'form': form, 'printout': error_msg, 'ships': ships
  })


@login_required(login_url='/fund/login/')
@approved_membership()
def set_current(request, ship_id):
  member = request.membership.member
  try:
    ship = models.Membership.objects.get(pk=ship_id, member=member, approved=True)
  except models.Membership.DoesNotExist:
    return redirect(manage_account)

  member.current = ship.pk
  member.save()

  return redirect(home)

#-----------------------------------------------------------------------------
# ERROR & HELP PAGES
#-----------------------------------------------------------------------------

@login_required(login_url='/fund/login/')
def not_member(request):
  try:
    org = Organization.objects.get(email=request.user.username)
  except Organization.DoesNotExist:
    org = False

  return render(request, 'fund/not_member.html', {
    'contact_url': '/fund/support#contact', 'org': org
  })


@login_required(login_url='/fund/login/')
def not_approved(request):
  try:
    models.Member.objects.get(email=request.user.username)
  except models.Member.DoesNotExist:
    return redirect(not_member)

  return render(request, 'fund/not_approved.html')


def blocked(request):
  return render(request, 'fund/blocked.html', {
    'contact_url': '/fund/support#contact'
  })


def support(request):
  member = False
  if request.membership_status > c.NO_MEMBERSHIP:
    member = request.membership.member
  elif request.membership_status == c.NO_MEMBERSHIP:
    member = models.Member.objects.get(email=request.user.username)

  return render(request, 'fund/support.html', {
    'member': member, 'support_email': c.SUPPORT_EMAIL,
    'support_form': c.FUND_SUPPORT_FORM
  })

#-----------------------------------------------------------------------------
# SURVEY
#-----------------------------------------------------------------------------

@login_required(login_url='/fund/login')
@approved_membership()
def project_survey(request, gp_survey_id):

  try:
    gp_survey = models.GPSurvey.objects.get(pk=gp_survey_id)
  except models.GPSurvey.DoesNotExist:
    logger.error('GP Survey does not exist ' + str(gp_survey))
    raise Http404('survey not found')

  if request.method == 'POST':
    logger.info(request.POST)
    form = modelforms.SurveyResponseForm(gp_survey.survey, request.POST)
    if form.is_valid():
      form.save()
      logger.info('survey response saved')
      completed = json.loads(request.membership.completed_surveys)
      completed.append(gp_survey.pk)
      request.membership.completed_surveys = json.dumps(completed)
      request.membership.save()
      return HttpResponse('success')

  else: # GET
    form = modelforms.SurveyResponseForm(gp_survey.survey,
                                         initial={'gp_survey': gp_survey})

  steps, news, grants = _get_block_content(request.membership)

  return render(request, 'fund/forms/gp_survey.html', {
    'form': form, 'survey': gp_survey.survey, 'news': news,
    'steps': steps, 'grants': grants
  })

#-----------------------------------------------------------------------------
# CONTACTS
#-----------------------------------------------------------------------------

@login_required(login_url='/fund/login')
@approved_membership()
def copy_contacts(request):

  # base formset
  copy_formset = formset_factory(forms.CopyContacts, extra=0)

  if request.method == 'POST':
    logger.info(request.POST)

    if 'skip' in request.POST:
      logger.info('User skipping copy contacts')
      request.membership.copied_contacts = True
      request.membership.save()
      return HttpResponse("success")

    else:
      formset = copy_formset(request.POST)
      logger.info('Copy contracts submitted')
      if formset.is_valid():
        for form in formset.cleaned_data:
          if form['select']:
            contact = models.Donor(membership=request.membership,
                firstname=form['firstname'], lastname=form['lastname'],
                phone=form['phone'], email=form['email'], notes=form['notes'])
            contact.save()
            logger.debug('Contact created')
        request.membership.copied_contacts = True
        request.membership.save()
        return HttpResponse("success")
      else: # invalid
        logger.warning('Copy formset somehow invalid?! ' + str(request.POST))
        logger.warning(formset.errors)

  else: # GET
    all_donors = (models.Donor.objects.filter(membership__member=request.membership.member)
                                      .order_by('firstname', 'lastname', '-added'))

    # extract name, contact info, notes. handle duplicates
    initial_data = []
    for donor in all_donors:
      # TODO make function for this check
      if (initial_data and donor.firstname == initial_data[-1]['firstname'] and
             (donor.lastname and donor.lastname == initial_data[-1]['lastname'] or
                 donor.phone and donor.phone == initial_data[-1]['phone'] or
                 donor.email and donor.email == initial_data[-1]['email'])):
        logger.info('Duplicate found! ' + str(donor))
        initial_data[-1]['lastname'] = initial_data[-1]['lastname'] or donor.lastname
        initial_data[-1]['phone'] = initial_data[-1]['phone'] or donor.phone
        initial_data[-1]['email'] = initial_data[-1]['email'] or donor.email
        initial_data[-1]['notes'] += donor.notes
        initial_data[-1]['notes'] = initial_data[-1]['notes'][:253] # cap below field char limit

      else: # not duplicate; add a row
        initial_data.append({
            'firstname': donor.firstname, 'lastname': donor.lastname,
            'phone': donor.phone, 'email': donor.email, 'notes': donor.notes})

    logger.debug('Loading copy contacts formset')
    logger.info('Initial data list of ' + str(len(initial_data)))
    formset = copy_formset(initial=initial_data)

  return render(request, 'fund/forms/copy_contacts.html', {'formset': formset})


@login_required(login_url='/fund/login/')
@approved_membership()
def add_mult(request):
  """ Add multiple contacts, with or without estimates

    If a user enters duplicates (same first & last name), they'll get a
      confirmation form before donors are saved

    GET is via redirect from home, and should render top blocks as well as form
    POST will be via AJAX and does not need block info
  """
  membership = request.membership

  est = membership.giving_project.require_estimates()
  if est:
    contact_formset = formset_factory(forms.MassDonor, extra=5)
  else:
    contact_formset = formset_factory(forms.MassDonorPre, extra=5)

  empty_error = ''

  if request.method == 'POST':
    membership.last_activity = timezone.now()
    membership.save()

    formset = contact_formset(request.POST)

    if formset.is_valid():

      if formset.has_changed():
        logger.info('AddMult valid formset')

        # get list of existing donors to check for duplicates
        donors = models.Donor.objects.filter(membership=membership)
        donors = [unicode(donor) for donor in donors]
        duplicates = []

        for form in formset.cleaned_data:
          if form: # ignore blank rows
            confirm = form['confirm'] and form['confirm'] == '1'

            if not confirm and (form['firstname'] + ' ' + form['lastname'] in donors):
              # this entry is a duplicate that has not yet been confirmed
              initial = {'firstname': form['firstname'],
                         'lastname': form['lastname'],
                         'confirm': u'1'}
              if est:
                initial['amount'] = form['amount']
                initial['likelihood'] = form['likelihood']
              duplicates.append(initial)

            else: # not a duplicate
              if est:
                contact = models.Donor(membership=membership,
                    firstname=form['firstname'], lastname=form['lastname'],
                    amount=form['amount'], likelihood=form['likelihood'])
              else:
                contact = models.Donor(membership=membership,
                    firstname=form['firstname'], lastname=form['lastname'])
              contact.save()
              logger.info('contact created')

        if duplicates:
          logger.info('Showing confirmation page for duplicates: ' + str(duplicates))
          empty_error = ('<ul class="errorlist"><li>The contacts below have the '
              'same name as contacts you have already entered. Press submit again '
              'to confirm that you want to add them.</li></ul>')
          if est:
            contact_formset = formset_factory(forms.MassDonor)
          else:
            contact_formset = formset_factory(forms.MassDonorPre)
          formset = contact_formset(initial=duplicates)

        else: # saved successfully (no duplicates check needed)
          return HttpResponse("success")

      else: # empty formset
        empty_error = u'<ul class="errorlist"><li>Please enter at least one contact.</li></ul>'

    else: # invalid formset
      logger.info(formset.errors)

    return render(request, 'fund/forms/add_contacts.html', {
      'formset': formset, 'empty_error': empty_error
    })

  else: # GET
    formset = contact_formset()
    steps, news, grants = _get_block_content(membership)
    header = membership.giving_project.title

    return render(request, 'fund/forms/add_contacts.html', {
      '1active': 'true', 'header': header, 'news': news,
      'grants': grants, 'steps': steps, 'formset': formset
    })


@login_required(login_url='/fund/login/')
@approved_membership()
def add_estimates(request):
  membership = request.membership

  initial_form_data = []
  donor_names = [] # to display with forms (which only have pks)

  # get all donors without estimates
  for donor in membership.donor_set.filter(amount__isnull=True):
    initial_form_data.append({'donor': donor})
    donor_names.append(unicode(donor))

  # create formset
  est_formset = formset_factory(forms.DonorEstimates, extra=0)

  if request.method == 'POST':
    membership.last_activity = timezone.now()
    membership.save(skip=True)
    formset = est_formset(request.POST)
    logger.debug('Adding estimates - posted: ' + str(request.POST))

    if formset.is_valid():
      logger.debug('Adding estimates - is_valid passed, cycling through forms')
      for form in formset.cleaned_data:
        if form:
          donor = form['donor']
          donor.amount = form['amount']
          donor.likelihood = form['likelihood']
          donor.save()
      return HttpResponse("success")

    else: # invalid form
      formset_with_donors = zip(formset, donor_names)
      return render(request, 'fund/forms/add_estimates.html', {
        'formset': formset, 'fd': formset_with_donors
      })

  else: # GET
    formset = est_formset(initial=initial_form_data)
    logger.info('Adding estimates - loading initial formset, size ' +
                 str(len(donor_names)))

    # get vars for base templates
    steps, news, grants = _get_block_content(membership)

    formset_with_donors = zip(formset, donor_names)

    return render(request, 'fund/forms/add_estimates.html', {
      'news': news, 'grants': grants, 'steps': steps,
      '1active': 'true', 'formset': formset, 'fd': formset_with_donors
    })


@login_required(login_url='/fund/login/')
@approved_membership()
def edit_contact(request, donor_id):

  try:
    donor = models.Donor.objects.get(pk=donor_id, membership=request.membership)
  except models.Donor.DoesNotExist:
    logger.error('Tried to edit a nonexist donor. User: ' +
                  unicode(request.membership) + ', id given: ' + str(donor_id))
    raise Http404

  # check whether to require estimates
  est = request.membership.giving_project.require_estimates()

  if request.method == 'POST':
    logger.debug(request.POST)
    request.membership.last_activity = timezone.now()
    request.membership.save(skip=True)
    if est:
      form = modelforms.DonorForm(request.POST, instance=donor,
                              auto_id=str(donor.pk) + '_id_%s')
    else:
      form = modelforms.DonorPreForm(request.POST, instance=donor,
                                 auto_id=str(donor.pk) + '_id_%s')
    if form.is_valid():
      logger.info('Edit donor success')
      form.save()
      return HttpResponse("success")
  else:
    if est:
      form = modelforms.DonorForm(instance=donor, auto_id=str(donor.pk) +
                              '_id_%s')
    else:
      form = modelforms.DonorPreForm(instance=donor, auto_id=str(donor.pk) +
                                 '_id_%s')
  return render(request, 'fund/forms/edit_contact.html',
                {'form': form, 'pk': donor.pk,
                 'action': '/fund/'+str(donor_id)+'/edit'})


@login_required(login_url='/fund/login/')
@approved_membership()
def delete_contact(request, donor_id):

  try:
    donor = models.Donor.objects.get(pk=donor_id, membership=request.membership)
  except models.Donor.DoesNotExist:
    logger.warning(str(request.user) + 'tried to delete nonexistent donor: ' +
                    str(donor_id))
    raise Http404

  action = '/fund/' + str(donor_id) + '/delete'

  if request.method == 'POST':
    request.membership.last_activity = timezone.now()
    request.membership.save(skip=True)
    donor.delete()
    return redirect(home)

  return render(request, 'fund/forms/delete_contact.html', {'action': action})

#-----------------------------------------------------------------------------
# STEPS
#-----------------------------------------------------------------------------

@login_required(login_url='/fund/login/')
@approved_membership()
def add_step(request, donor_id):

  membership = request.membership
  suggested = membership.giving_project.get_suggested_steps()

  logger.info('Single step - start of view. ' + unicode(membership.member) +
               ', donor id: ' + str(donor_id))

  try:
    donor = models.Donor.objects.get(pk=donor_id, membership=membership)
  except models.Donor.DoesNotExist:
    logger.error('Single step - tried to add step to nonexistent donor.')
    raise Http404

  if donor.get_next_step():
    logger.error('Trying to add step, donor has an incomplete')
    raise Http404 # TODO better error

  action = '/fund/' + donor_id + '/step'
  formid = 'addstep-'+donor_id
  divid = donor_id+'-addstep'

  if request.method == 'POST':
    membership.last_activity = timezone.now()
    membership.save(skip=True)
    form = modelforms.StepForm(request.POST, auto_id=str(donor.pk) + '_id_%s')
    logger.info('Single step - POST: ' + str(request.POST))
    if form.is_valid():
      step = form.save(commit=False)
      step.donor = donor
      step.save()
      logger.info('Single step - form valid, step saved')
      return HttpResponse("success")
  else:
    form = modelforms.StepForm(auto_id=str(donor.pk) + '_id_%s')

  return render(request, 'fund/forms/add_step.html',
                {'donor': donor, 'form': form, 'action': action, 'divid': divid,
                 'formid': formid, 'suggested': suggested,
                 'target': str(donor.pk) + '_id_description'})


@login_required(login_url='/fund/login/')
@approved_membership()
def add_mult_step(request):
  initial_form_data = [] # list of dicts for form initial
  donor_list = [] # list of donors for zipping to formset
  size = 0
  membership = request.membership
  suggested = membership.giving_project.get_suggested_steps()

  for donor in membership.donor_set.order_by('-added'): # sort by added
    if donor.received() == 0 and donor.promised is None and donor.get_next_step() is None:
      initial_form_data.append({'donor': donor})
      donor_list.append(donor)
      size = size +1
    if size > 9:
      break
  step_formset = formset_factory(forms.MassStep, extra=0)
  if request.method == 'POST':
    membership.last_activity = timezone.now()
    membership.save(skip=True)
    formset = step_formset(request.POST)
    logger.debug('Multiple steps - posted: ' + str(request.POST))
    if formset.is_valid():
      logger.debug('Multiple steps - is_valid passed, cycling through forms')
      for form in formset.cleaned_data:
        if form:
          step = models.Step(donor=form['donor'], date=form['date'],
                             description=form['description'])
          step.save()
          logger.info('Multiple steps - step created')
      return HttpResponse("success")
    else:
      logger.info('Multiple steps invalid')
  else:
    formset = step_formset(initial=initial_form_data)
    logger.info('Multiple steps - loading initial formset, size ' + str(size) +
                 ': ' +str(donor_list))
  formset_with_donors = zip(formset, donor_list)
  return render(request, 'fund/forms/add_mult_step.html',
                {'size': size, 'formset': formset, 'fd': formset_with_donors, 'multi': True,
                 'suggested': suggested})


@login_required(login_url='/fund/login/')
@approved_membership()
def edit_step(request, donor_id, step_id):

  suggested = request.membership.giving_project.get_suggested_steps()

  try:
    donor = models.Donor.objects.get(pk=donor_id,
                                     membership=request.membership)
  except models.Donor.DoesNotExist:
    logger.error(str(request.user) + 'edit step on nonexistent donor ' +
                  str(donor_id))
    raise Http404

  try:
    step = models.Step.objects.get(id=step_id)
  except models.Step.DoesNotExist:
    logger.error(str(request.user) + 'edit step on nonexistent step ' +
                  str(step_id))
    raise Http404

  action = '/fund/'+str(donor_id)+'/'+str(step_id)
  formid = 'edit-step-'+donor_id
  divid = donor_id+'-nextstep'

  if request.method == 'POST':
    request.membership.last_activity = timezone.now()
    request.membership.save(skip=True)
    form = modelforms.StepForm(request.POST, instance=step, auto_id=str(step.pk) +
                           '_id_%s')
    if form.is_valid():
      logger.debug('Edit step success')
      form.save()
      return HttpResponse("success")
  else:
    form = modelforms.StepForm(instance=step, auto_id=str(step.pk) + '_id_%s')

  return render(request, 'fund/forms/edit_step.html', {
    'donor': donor, 'form': form, 'action': action, 'divid': divid,
    'formid': formid, 'suggested': suggested,
    'target': str(step.pk) + '_id_description'
  })


@login_required(login_url='/fund/login/')
@approved_membership()
def complete_step(request, donor_id, step_id):

  membership = request.membership
  suggested = membership.giving_project.get_suggested_steps()

  try:
    donor = models.Donor.objects.get(pk=donor_id, membership=membership)
  except models.Donor.DoesNotExist:
    logger.error(str(request.user) + ' complete step on nonexistent donor ' +
                  str(donor_id))
    raise Http404

  try:
    step = models.Step.objects.get(id=step_id, donor=donor)
  except models.Step.DoesNotExist:
    logger.error(str(request.user) + ' complete step on nonexistent step ' +
                  str(step_id))
    raise Http404

  action = reverse('sjfnw.fund.views.complete_step', kwargs={'donor_id': donor_id, 'step_id': step_id})

  if request.method == 'POST':
    # update membership activity timestamp
    membership.last_activity = timezone.now()
    membership.save(skip=True)

    # get posted form
    form = forms.StepDoneForm(request.POST, auto_id=str(step.pk) + '_id_%s')
    if form.is_valid():
      logger.info('Completing a step')

      step.completed = timezone.now()
      donor.talked = True
      donor.notes = form.cleaned_data['notes']

      asked = form.cleaned_data['asked']
      response = form.cleaned_data['response']
      promised = form.cleaned_data['promised_amount']

      # process ask-related input
      if asked:
        if not donor.asked: # asked this step
          logger.debug('Asked this step')
          step.asked = True
          donor.asked = True
        if response == '3': # declined, doesn't matter this step or not
          donor.promised = 0
          step.promised = 0
          logger.debug('Declined')
        if response == '1' and promised and not donor.promised: # pledged this step
          logger.debug('Promise entered')
          step.promised = promised
          donor.promised = promised
          donor.lastname = form.cleaned_data['last_name']
          donor.likely_to_join = form.cleaned_data['likely_to_join']
          logger.info(form.cleaned_data['likely_to_join'])
          donor.promise_reason = json.dumps(form.cleaned_data['promise_reason'])
          logger.info(form.cleaned_data['promise_reason'])
          phone = form.cleaned_data['phone']
          email = form.cleaned_data['email']
          if phone:
            donor.phone = phone
          if email:
            donor.email = email

      # save donor & completed step
      step.save()
      donor.save()

      # call story creator/updater
      if os.getenv('SERVER_SOFTWARE', '').startswith('Google App Engine'):
        deferred.defer(membership.update_story, timezone.now())
        logger.info('Calling update story')

      # process next step input
      next_step = form.cleaned_data['next_step']
      next_date = form.cleaned_data['next_step_date']
      if next_step != '' and next_date != None:
        form2 = modelforms.StepForm().save(commit=False)
        form2.date = next_date
        form2.description = next_step
        form2.donor = donor
        form2.save()
        logger.info('Next step created')

      return HttpResponse("success")
    else: # invalid form
      logger.info('Invalid step completion: ' + str(form.errors))

  else: # GET - fill form with initial data
    initial = {
      'asked': donor.asked, 'notes': donor.notes, 'last_name': donor.lastname,
      'phone': donor.phone, 'email': donor.email,
      'promise_reason': json.loads(donor.promise_reason),
      'likely_to_join': donor.likely_to_join
    }
    if donor.promised:
      if donor.promised == 0:
        initial['response'] = 3
      else:
        initial['response'] = 1
        initial['promised_amount'] = donor.promised
    form = forms.StepDoneForm(auto_id=str(step.pk) + '_id_%s', initial=initial)

  return render(request, 'fund/forms/complete_step.html',
                {'form': form, 'action': action, 'donor': donor,
                 'suggested': suggested,
                 'target': str(step.pk) + '_id_next_step', 'step_id': step_id,
                 'step': step})

#-----------------------------------------------------------------------------
# METHODS USED BY MULTIPLE VIEWS
#-----------------------------------------------------------------------------

def _get_block_content(membership, get_steps=True):
  """ Provide upper block content for the 3 main views

  Args:
    membership: current Membership
    get_steps: include list of upcoming steps or not

  Returns: Tuple:
    steps: 2 closest upcoming steps (None if get_steps=False)
    news: news items, sorted by date descending
    grants: ProjectApps ordered by org name
  """

  steps, news, grants = None, None, None
  # upcoming steps
  if get_steps:
    steps = (models.Step.objects
        .select_related('donor')
        .filter(donor__membership=membership, completed__isnull=True)
        .order_by('date')[:2])

  # project news
  news = (models.NewsItem.objects
      .filter(membership__giving_project=membership.giving_project)
      .order_by('-date')[:25])

  # grants
  p_apps = ProjectApp.objects.filter(giving_project=membership.giving_project)
  p_apps = p_apps.select_related('giving_project', 'application',
      'application__organization')
  # never show screened out by sub-committee
  p_apps = p_apps.exclude(application__pre_screening_status=45)
  if membership.giving_project.site_visits == 1:
    logger.info('Filtering grants for site visits')
    p_apps = p_apps.filter(screening_status__gte=70)
  grants = p_apps.order_by('application__organization__name')

  return steps, news, grants

def _create_user(email, password, first_name, last_name):
  user, member, error = None, None, None

  # check if Member already
  if models.Member.objects.filter(email=email):
    error = 'That email is already registered.  <a href="/fund/login/">Login</a> instead.'
    logger.warning(email + ' tried to re-register')

  # check User already but not Member
  elif User.objects.filter(username=email):
    error = ('That email is already registered through Social Justice Fund\'s '
        'online grant application.  Please use a different email address.')
    logger.warning('User already exists, but not Member: ' + email)

  else:
    # ok to register - create User and Member
    user = User.objects.create_user(email, email, password)
    user.first_name = first_name
    user.last_name = last_name
    user.save()
    member = models.Member(email=email, first_name=first_name,
                           last_name=last_name)
    member.save()
    logger.info('Registration - user and member objects created for ' + email)

  return user, member, error

def _create_membership(member, giving_project, notif=''):
  error = None

  approved = giving_project.is_pre_approved(member.email)

  membership, new = models.Membership.objects.get_or_create(
      member=member, giving_project=giving_project,
      defaults={'approved': approved, 'notifications': notif})

  if not new:
    error = 'You are already registered with that giving project.'
  else:
    member.current = membership.pk
    member.save()

  return membership, error

