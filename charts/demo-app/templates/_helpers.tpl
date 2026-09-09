{{- define "demo.image" -}}
{{- $digest := required "image.digest must be an immutable sha256 digest" .Values.image.digest -}}
{{- if not (regexMatch "^sha256:[a-f0-9]{64}$" $digest) -}}
{{- fail "image.digest must be sha256 followed by 64 lowercase hex characters" -}}
{{- end -}}
{{- printf "%s@%s" .Values.image.repository $digest -}}
{{- end -}}

{{- define "demo.labels" -}}
app.kubernetes.io/part-of: previewforge
app.kubernetes.io/instance: {{ .Release.Name }}
previewforge.io/environment: {{ .Values.environment | quote }}
{{- end -}}

{{- define "demo.environment" -}}
- name: DATABASE_HOST
  value: {{ printf "%s-postgres" .Release.Name | quote }}
- name: DATABASE_PORT
  value: {{ .Values.database.port | quote }}
- name: DATABASE_NAME
  value: {{ .Values.database.name | quote }}
- name: DATABASE_USER
  value: {{ .Values.database.user | quote }}
- name: DATABASE_PASSWORD_FILE
  value: /run/secrets/db_password
- name: ENVIRONMENT_NAME
  value: {{ .Values.environment | quote }}
{{- end -}}

{{- define "demo.security" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile: {type: RuntimeDefault}
{{- end -}}
