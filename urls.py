﻿from django.conf.urls import patterns, include
from django.views.generic.simple import direct_to_template
from admin import advanced_admin
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
import grants, fund
from django.conf import settings

urlpatterns = patterns('',

## ADMIN ##

    (r'^admin/', include(admin.site.urls)),
    (r'^admin-advanced/', include(advanced_admin.urls)),

## LANDING ##    

    (r'^$', 'django.views.generic.simple.direct_to_template', {'template': 'home.html'}),
    
## GRANTS - ORGANIZATION VIEWS ##
    
    #login, logout, registration
    (r'^org/login/?$', 'grants.views.OrgLogin'),
    (r'^org/register/?$', 'grants.views.OrgRegister'),
    (r'^org/nr', direct_to_template, {'template': 'grants/not_grantee.html'}),
    (r'^logout/?$', 'django.contrib.auth.views.logout', {'next_page': '/org'}),

    #reset password
    (r'^org/reset$', 'django.contrib.auth.views.password_reset', {'template_name':'grants/reset.html', 'from_email':settings.DEFAULT_FROM_EMAIL, 'email_template_name':'grants/password_reset_email.html'}),
    (r'^org/reset-sent', 'django.contrib.auth.views.password_reset_done', {'template_name':'grants/password_reset_done.html'}),
    (r'^org/reset/(?P<uidb64>[0-9A-Za-z]+)-(?P<token>.+)/?$', 'django.contrib.auth.views.password_reset_confirm', {'template_name':'grants/password_reset_confirm.html'}),
    (r'^org/reset-complete', 'django.contrib.auth.views.password_reset_complete', {'template_name':'grants/password_reset_complete.html'}),
     
     #main pages
    (r'^org/?$','grants.views.OrgHome'),
    (r'^org/support', 'grants.views.OrgSupport'),
    
    #application
    (r'^apply/(?P<cycle_id>\d+)/?$','grants.views.Apply'),
    (r'^apply/(?P<cycle_id>\d+)/autosave/?$','grants.views.AutoSaveApp'),
    (r'^apply/(?P<cycle_id>\d+)/upload-file/?$','grants.views.AutoSaveFile'),
    (r'^apply/(?P<cycle_id>\d+)/DELETE$', 'grants.views.DiscardDraft'),
    (r'^get-upload-url/(?P<cycle_id>\d+)/?$','grants.views.RefreshUploadUrl'),
    (r'^org/submitted.html', direct_to_template, {'template': 'grants/submitted.html'}),
    
    #cron
    (r'^mail/drafts', 'grants.views.DraftWarning'),

## GRANTS - APPLICATION VIEWS ##

    (r'^grants/view/(?P<app_id>\d+)/?$', 'grants.views.ViewApplication'),
    (r'^grants/download/(?P<app_id>\d+)/(?P<file_type>.*)$', 'grants.views.ViewFile'),
    
## GRANTS - REPORTING ##
  
    (r'^grants/grant_application/?$', 'grants.search.search'),
    (r'^grants/grant_application/search', 'grants.search.search'),
    (r'^grants/grant_application/results', 'grants.search.results'),
    (r'^grants/grant_application/(?P<grant_application_id>\d+)/?$', 'grants.search.show'),

    # These endpoints return the serialized json form of these models
    (r'^grants/api/grant_application/results',
            'grants.search.api_grant_applications'),

    (r'^grants/api/grant_application/(?P<grant_application_id>\d+)/?$',
        'grants.search.api_show_grant_application'),

    (r'^grants/api/grantee/(?P<grantee_id>\d+)/?$',
        'grants.search.api_show_grantee'),

    (r'^grants/api/grant_cycle/(?P<grant_cycle_id>\d+)/?$',
        'grants.search.api_show_grant_cycle'),

    # Endpoint for csv
    (r'^grants/csv/grant_application/results',
        'grants.search.csv_grant_applications'),

    (r'^grants/csv/grant_application/(?P<grant_application_id>\d+)/?$',
        'grants.search.csv_show_grant_application'),

## SCORING ##

    (r'^scoring/projectlist/', 'scoring.views.all_giving_projects'),
    (r'^scoring/projectsummary/(?P<project_id>\d+)/?$', 'scoring.views.specific_project_admin'),
    (r'^scoring/reading/(?P<app_id>\d+)/?$', 'scoring.views.read_grant'),
    (r'scoring/save$', 'scoring.views.Save'),
    # (r'^fund/scoring', 'fund.views.ScoringList') --located under main pages

## FUNDRAISING ##
    
    #login, logout, registration
    (r'^fund/login/?$', 'fund.views.FundLogin'),
    (r'^fund/logout/?$', 'django.contrib.auth.views.logout', {'next_page': '/fund'}),
    (r'^fund/register/?$', 'fund.views.Register'),
    (r'^fund/registered/?$', 'fund.views.Registered'),
    
    #reset password
    (r'^fund/reset$', 'django.contrib.auth.views.password_reset', {'template_name':'fund/reset.html', 'from_email':'webmaster@socialjusticefund.org', 'email_template_name':'fund/password_reset_email.html', 'subject_template_name':'registration/password_reset_subject.txt'}),
    (r'^fund/reset-sent', 'django.contrib.auth.views.password_reset_done', {'template_name':'fund/password_reset_done.html'}),
    (r'^fund/reset/(?P<uidb64>[0-9A-Za-z]+)-(?P<token>.+)/?$', 'django.contrib.auth.views.password_reset_confirm', {'template_name':'fund/password_reset_confirm.html'}),
    (r'^fund/reset-complete', 'django.contrib.auth.views.password_reset_complete', {'template_name':'fund/password_reset_complete.html'}),
    
    #manage memberships
    (r'^fund/projects', 'fund.views.Projects'),
    (r'^fund/set-current/(?P<ship_id>\d+)/', 'fund.views.SetCurrent'),
    
    #main pages
    (r'^fund/?$', 'fund.views.Home'),
    (r'^fund/gp', 'fund.views.ProjectPage'),
    (r'^fund/scoring', 'fund.views.ScoringList'),
    
    #forms - contacts
    (r'^fund/addmult', 'fund.views.AddMult'),
    (r'^fund/(?P<donor_id>\d+)/edit','fund.views.EditDonor'),
    (r'^fund/(?P<donor_id>\d+)/delete', 'fund.views.DeleteDonor'),
    (r'^fund/add-estimates', 'fund.views.AddEstimates'),
    
    #forms - steps
    (r'^fund/(?P<donor_id>\d+)/step$','fund.views.AddStep'),
    (r'^fund/stepmult$','fund.views.AddMultStep'),
    (r'^fund/(?P<donor_id>\d+)/(?P<step_id>\d+)/?$','fund.views.EditStep'),
    (r'^fund/(?P<donor_id>\d+)/(?P<step_id>\d+)/done','fund.views.DoneStep'),
    
    #error/help pages
    (r'^fund/not-member', 'fund.views.NotMember'),
    (r'^fund/pending$', 'fund.views.NotApproved'),
    (r'^fund/support', 'fund.views.Support'),
    (r'^fund/blocked$', 'fund.views.Blocked'),
    
    #cron
    (r'^mail/overdue-step', 'fund.views.EmailOverdue'),
    (r'^mail/new-accounts', 'fund.views.NewAccounts'),
    (r'^mail/gifts', 'fund.views.GiftNotify'),
    
## DEVEL ##

    (r'test/?$', 'grants.views.TestView'),
  )

  #for devel since using appengine
urlpatterns += staticfiles_urlpatterns()
