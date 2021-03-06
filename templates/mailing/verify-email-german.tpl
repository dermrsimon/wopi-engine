{% extends "mail_templated/base.tpl" %}

{% block subject %}
Bestätigung Deiner E-Mail Adresse bei SPARDA Versicherungen
{% endblock %}

{% block html %}

<style>
    .button {
        border-radius: 2px;
    }

    .button a {
        padding: 8px 12px;
        border: 1px solid #E87405;
        border-radius: 2px;
        font-family: Helvetica, Arial, sans-serif;
        font-size: 14px;
        color: #ffffff;
        text-decoration: none;
        font-weight: bold;
        display: inline-block;
}

</style>

Hallo {{ user.first_name }}!
<p>Hier ist die Mail zum Bestätigen Deiner E-Mail Adresse.</p>
<p>Um Deine E-Mail Adresse zu bestätigen, klick bitte auf folgenden Link:</p>


<table width="100%" cellspacing="0" cellpadding="0">
    <tr>
        <td>
            <table cellspacing="0" cellpadding="0">
                <tr>
                    <td class="button" bgcolor="#E87405">
                        <a class="link" href="https://app.spardaplus.at/verify/{{ token }}">E-Mail Adresse bestätigen</a>
                    </td>
                </tr>
            </table>
        </td>
    </tr>
</table>

<p>Mit freundlichen Grüßen<br>
Dein SPARDA Team</p>
{% endblock %}