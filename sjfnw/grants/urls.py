from django.conf.urls import patterns, include
from django.views.generic.base import TemplateView
from sjfnw import constants

# apply urls will all be prefixed with 'apply/' in mail url file

apply_urls = patterns('',
  (r'^nr', TemplateView.as_view(template_name ='grants/not_grantee.html')),
  (r'^submitted/?', TemplateView.as_view(template_name='grants/submitted.html')),
)

apply_urls += patterns('sjfnw.grants.views',

  #login, logout, registration
  (r'^login/?$', 'org_login'),
  (r'^register/?$', 'org_register'),

  #home page
  (r'^$','org_home'),
  (r'^(?P<draft_id>\d+)/DELETE/?$', 'DiscardDraft'),
  (r'^copy/?$', 'CopyApp'),
  (r'^support/?', 'org_support'),

  #application
  (r'^(?P<cycle_id>\d+)/?$','Apply'),
  (r'^info/(?P<cycle_id>\d+)/?$','cycle_info'),

  #application ajax
  (r'^(?P<draft_id>\d+)/add-file/?$', 'AddFile'),
  (r'^(?P<draft_id>\d+)/remove/(?P<file_field>.*)/?$', 'RemoveFile'),
  (r'^(?P<cycle_id>\d+)/autosave/?$','autosave_app'),
)

apply_urls += patterns('',
  # password reset
  (r'^reset/?$', 'django.contrib.auth.views.password_reset', {'template_name':'grants/reset.html', 'from_email':constants.GRANT_EMAIL, 'email_template_name':'grants/password_reset_email.html', 'post_reset_redirect':'/apply/reset-sent'}),
  (r'^reset-sent/?$', 'django.contrib.auth.views.password_reset_done', {'template_name':'grants/password_reset_done.html'}),
  (r'^reset/(?P<uidb36>[0-9A-Za-z]+)-(?P<token>.+)/?$', 'django.contrib.auth.views.password_reset_confirm', {'template_name':'grants/password_reset_confirm.html', 'post_reset_redirect': '/apply/reset-complete'}, 'org-reset'),
  (r'^reset-complete/?', 'django.contrib.auth.views.password_reset_complete', {'template_name':'grants/password_reset_complete.html'}),
)

# grants urls will all be prefixed with 'grants/' in mail url file

grants_urls = patterns('sjfnw.grants.views',
  #reading
  (r'^view/(?P<app_id>\d+)/?$', 'ReadApplication'),
  (r'^view-file/(?P<app_id>\d+)-(?P<file_type>.*)\.', 'ViewFile'),
  (r'^draft-file/(?P<draft_id>\d+)-(?P<file_type>.*)\.', 'ViewDraftFile'),
)
