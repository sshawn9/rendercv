{% if cv.name %}
# {{ cv.name }}'s CV
{% endif %}

{% if cv.phone %}
    {% for phone in ([cv.phone] if cv.phone is string else cv.phone) %}
- Phone: {{phone|replace("tel:", "")|replace("-"," ")}}
    {% endfor %}
{% endif %}
{% if cv.email %}
    {% for email in ([cv.email] if cv.email is string else cv.email) %}
- Email: [{{email}}](mailto:{{email}})
    {% endfor %}
{% endif %}
{% if cv.location %}
- Location: {{cv.location}}
{% endif %}
{% if cv.website %}
    {% for website in (cv.website if cv.website is sequence and cv.website is not string else [cv.website]) %}
- Website: [{{website|string|clean_url}}]({{website}})
    {% endfor %}
{% endif %}
{% if cv.social_networks %}
    {% for network in cv.social_networks %}
- {{network.network}}: [{{network.username}}]({{network.url}})
    {% endfor %}
{% endif %}
{% if cv.custom_connections %}
    {% for connection in cv.custom_connections %}
        {% if connection.url %}
- [{{connection.placeholder}}]({{connection.url}})
        {% else %}
- {{connection.placeholder}}
        {% endif %}
    {% endfor %}
{% endif %}
