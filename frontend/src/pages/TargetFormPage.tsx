import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Braces, Check, Eye, EyeOff, Info, LockKeyhole, Save } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ErrorState, PageLoader } from '../components/AsyncState'
import { PageHeader } from '../components/PageHeader'
import { api } from '../lib/api'
import type { TargetInput } from '../types/api'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

interface FormValues {
  name: string
  endpointUrl: string
  apiKey: string
  requestTemplate: string
  promptField: string
  responseField: string
}

type FormErrors = Partial<Record<keyof FormValues, string>>

const initialValues: FormValues = {
  name: '',
  endpointUrl: '',
  apiKey: '',
  requestTemplate: '{\n  "message": ""\n}',
  promptField: 'message',
  responseField: 'response',
}

function validate(values: FormValues): FormErrors {
  const errors: FormErrors = {}
  if (!values.name.trim()) errors.name = 'Enter an application name.'
  if (!values.endpointUrl.trim()) {
    errors.endpointUrl = 'Enter the target API endpoint.'
  } else {
    try {
      const parsed = new URL(values.endpointUrl)
      if (!['http:', 'https:'].includes(parsed.protocol)) errors.endpointUrl = 'Use an http:// or https:// URL.'
    } catch {
      errors.endpointUrl = 'Enter a valid absolute URL, including http:// or https://.'
    }
  }
  if (!values.promptField.trim()) errors.promptField = 'Enter the field where prompts should be inserted.'
  if (!values.responseField.trim()) errors.responseField = 'Enter the field where responses can be found.'
  try {
    const parsed: unknown = JSON.parse(values.requestTemplate)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      errors.requestTemplate = 'The template must be a JSON object.'
    }
  } catch {
    errors.requestTemplate = 'Enter valid JSON.'
  }
  return errors
}

export function TargetFormPage() {
  const { targetId } = useParams()
  const parsedId = Number(targetId)
  const editing = Boolean(targetId)
  useDocumentTitle(editing ? 'Edit target' : 'Register target')
  const navigate = useNavigate()
  const [values, setValues] = useState<FormValues>(initialValues)
  const [errors, setErrors] = useState<FormErrors>({})
  const [loading, setLoading] = useState(editing)
  const [loadError, setLoadError] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [saving, setSaving] = useState(false)
  const [showApiKey, setShowApiKey] = useState(false)
  const [hasApiKey, setHasApiKey] = useState(false)
  const [clearApiKey, setClearApiKey] = useState(false)
  const [templateValid, setTemplateValid] = useState(true)

  useEffect(() => {
    if (!editing || !Number.isInteger(parsedId)) {
      if (editing) {
        setLoadError('This target ID is not valid.')
        setLoading(false)
      }
      return
    }
    let active = true
    api
      .getTarget(parsedId)
      .then((target) => {
        if (!active) return
        setHasApiKey(target.has_api_key)
        setClearApiKey(false)
        setValues({
          name: target.name,
          endpointUrl: target.endpoint_url,
          apiKey: '',
          requestTemplate: JSON.stringify(target.request_template, null, 2),
          promptField: target.prompt_field,
          responseField: target.response_field,
        })
      })
      .catch((error) => active && setLoadError(error instanceof Error ? error.message : 'Unable to load the target.'))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [editing, parsedId])

  const backPath = editing && Number.isInteger(parsedId) ? `/targets/${parsedId}` : '/targets'
  const title = editing ? 'Edit target' : 'Register a target'
  const description = editing
    ? 'Update how Sentinel communicates with this application.'
    : 'Configure the HTTP contract Sentinel will use during security evaluations.'

  const formattedTemplate = useMemo(() => {
    try {
      return JSON.stringify(JSON.parse(values.requestTemplate), null, 2)
    } catch {
      return null
    }
  }, [values.requestTemplate])

  function updateField(field: keyof FormValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
    if (field === 'requestTemplate') {
      try {
        const parsed: unknown = JSON.parse(value)
        setTemplateValid(Boolean(parsed && typeof parsed === 'object' && !Array.isArray(parsed)))
      } catch {
        setTemplateValid(false)
      }
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const nextErrors = validate(values)
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length > 0) {
      document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
      return
    }

    setSaving(true)
    setSubmitError('')
    const payload: TargetInput = {
      name: values.name.trim(),
      endpoint_url: values.endpointUrl.trim(),
      http_method: 'POST',
      request_template: JSON.parse(values.requestTemplate) as Record<string, unknown>,
      prompt_field: values.promptField.trim(),
      response_field: values.responseField.trim(),
      ...(clearApiKey ? { api_key: null } : values.apiKey.trim() ? { api_key: values.apiKey.trim() } : {}),
    }

    try {
      const target = editing ? await api.updateTarget(parsedId, payload) : await api.createTarget(payload)
      navigate(`/targets/${target.id}`, { replace: true })
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Unable to save the target.')
      setSaving(false)
    }
  }

  if (loading) return <div className="page"><PageLoader label="Loading target configuration" /></div>
  if (loadError) return <div className="page"><ErrorState title="Target unavailable" message={loadError} /></div>

  return (
    <div className="page page--narrow">
      <Link className="back-link" to={backPath}><ArrowLeft size={16} />Back to {editing ? 'target' : 'targets'}</Link>
      <PageHeader eyebrow="Target configuration" title={title} description={description} />

      <form className="form-layout" onSubmit={handleSubmit} noValidate>
        {submitError && <div className="inline-alert inline-alert--error" role="alert">{submitError}</div>}

        <section className="form-section">
          <div className="form-section__header">
            <span className="form-section__number">01</span>
            <div><h2>Application</h2><p>Identify the service and where Sentinel can reach it.</p></div>
          </div>
          <div className="form-grid">
            <div className="field field--full">
              <label htmlFor="target-name">Application name</label>
              <input id="target-name" value={values.name} onChange={(event) => updateField('name', event.target.value)} placeholder="Customer support assistant" aria-invalid={Boolean(errors.name)} aria-describedby={errors.name ? 'target-name-error' : undefined} autoFocus />
              {errors.name && <span className="field__error" id="target-name-error">{errors.name}</span>}
            </div>
            <div className="field field--endpoint">
              <label htmlFor="endpoint-url">Endpoint URL</label>
              <input id="endpoint-url" type="url" value={values.endpointUrl} onChange={(event) => updateField('endpointUrl', event.target.value)} placeholder="http://localhost:8001/chat" aria-invalid={Boolean(errors.endpointUrl)} aria-describedby={errors.endpointUrl ? 'endpoint-url-error' : 'endpoint-url-help'} />
              {errors.endpointUrl ? <span className="field__error" id="endpoint-url-error">{errors.endpointUrl}</span> : <span className="field__help" id="endpoint-url-help">Use a test or staging endpoint when possible.</span>}
            </div>
            <div className="field field--method">
              <label htmlFor="http-method">Method</label>
              <select id="http-method" value="POST" disabled><option>POST</option></select>
            </div>
          </div>
        </section>

        <section className="form-section">
          <div className="form-section__header">
            <span className="form-section__number">02</span>
            <div><h2>Request mapping</h2><p>Define the request body and response extraction paths.</p></div>
          </div>
          <div className="field">
            <div className="field__label-row">
              <label htmlFor="request-template">Request JSON template</label>
              <span className={`json-status ${templateValid ? 'json-status--valid' : 'json-status--invalid'}`}>
                {templateValid && <Check size={13} />} {templateValid ? 'Valid JSON' : 'Invalid JSON'}
              </span>
            </div>
            <div className="code-field">
              <Braces size={17} aria-hidden="true" />
              <textarea id="request-template" rows={8} value={values.requestTemplate} onChange={(event) => updateField('requestTemplate', event.target.value)} onBlur={() => formattedTemplate && updateField('requestTemplate', formattedTemplate)} spellCheck={false} aria-invalid={Boolean(errors.requestTemplate)} aria-describedby={errors.requestTemplate ? 'request-template-error' : 'request-template-help'} />
            </div>
            {errors.requestTemplate ? <span className="field__error" id="request-template-error">{errors.requestTemplate}</span> : <span className="field__help" id="request-template-help">Sentinel safely parses this object; it never evaluates code.</span>}
          </div>
          <div className="form-grid form-grid--two">
            <div className="field">
              <label htmlFor="prompt-field">Prompt field / path</label>
              <input id="prompt-field" value={values.promptField} onChange={(event) => updateField('promptField', event.target.value)} placeholder="message" aria-invalid={Boolean(errors.promptField)} aria-describedby={errors.promptField ? 'prompt-field-error' : 'prompt-field-help'} />
              {errors.promptField ? <span className="field__error" id="prompt-field-error">{errors.promptField}</span> : <span className="field__help" id="prompt-field-help">Dot notation is supported, e.g. input.message.</span>}
            </div>
            <div className="field">
              <label htmlFor="response-field">Response field / path</label>
              <input id="response-field" value={values.responseField} onChange={(event) => updateField('responseField', event.target.value)} placeholder="response" aria-invalid={Boolean(errors.responseField)} aria-describedby={errors.responseField ? 'response-field-error' : 'response-field-help'} />
              {errors.responseField ? <span className="field__error" id="response-field-error">{errors.responseField}</span> : <span className="field__help" id="response-field-help">The path containing the assistant's text.</span>}
            </div>
          </div>
        </section>

        <section className="form-section">
          <div className="form-section__header">
            <span className="form-section__number">03</span>
            <div><h2>Authorization</h2><p>Optionally attach a bearer token to target requests.</p></div>
          </div>
          <div className="field">
            <label htmlFor="api-key">API key <span className="label-optional">Optional</span></label>
            <div className="input-with-action">
              <LockKeyhole size={17} aria-hidden="true" />
              <input id="api-key" type={showApiKey ? 'text' : 'password'} value={values.apiKey} disabled={clearApiKey} onChange={(event) => updateField('apiKey', event.target.value)} placeholder={editing ? 'Leave blank to keep the current key' : 'test_key_••••••••'} autoComplete="new-password" />
              <button type="button" onClick={() => setShowApiKey((shown) => !shown)} aria-label={showApiKey ? 'Hide API key' : 'Show API key'}>{showApiKey ? <EyeOff size={17} /> : <Eye size={17} />}</button>
            </div>
            {editing && hasApiKey && <label className="checkbox-field"><input type="checkbox" checked={clearApiKey} onChange={(event) => { setClearApiKey(event.target.checked); updateField('apiKey', '') }} /> Remove saved API key</label>}
            <div className="security-note"><Info size={15} aria-hidden="true" /><span>Keys are never returned by the API or shown again. Use fake or scoped test credentials for this MVP.</span></div>
          </div>
        </section>

        <div className="form-actions">
          <Link className="button button--secondary" to={backPath}>Cancel</Link>
          <button className="button button--primary" type="submit" disabled={saving}>
            {saving ? <span className="spinner spinner--small" aria-hidden="true" /> : <Save size={17} />}
            {saving ? 'Saving…' : editing ? 'Save changes' : 'Register target'}
          </button>
        </div>
      </form>
    </div>
  )
}
