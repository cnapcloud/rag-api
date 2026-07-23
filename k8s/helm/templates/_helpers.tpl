{{/*
Standard fullname helper, matching the convention every subchart dependency already
uses (fullnameOverride wins, else <release>-<chart> unless the release name already
contains the chart name). Defaults to "rag-api"/"rag-admin" via values.yaml so behavior
is unchanged unless fullnameOverride is explicitly set.
*/}}
{{- define "rag-api.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "rag-api.admin.fullname" -}}
{{- if .Values.admin.fullnameOverride -}}
{{- .Values.admin.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-admin" (include "rag-api.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
