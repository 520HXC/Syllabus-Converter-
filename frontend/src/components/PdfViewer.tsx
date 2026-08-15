import { useEffect, useState } from "react"
import { FileWarning, LoaderCircle } from "lucide-react"

import { useApi } from "../lib/api"
import { Card } from "./ui/Card"

export function PdfViewer({ documentId, filename }: { documentId: string; filename: string }) {
  const api = useApi()
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    setUrl(null)
    setError(null)
    api
      .getDocument(documentId)
      .then((blob) => {
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "The PDF could not be opened.")
      })
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [api, documentId])

  if (error) {
    return (
      <Card className="flex min-h-[32rem] items-center justify-center border-danger/20 bg-danger-soft p-6 text-center text-sm text-danger">
        <div>
          <FileWarning aria-hidden="true" className="mx-auto size-7" />
          <p className="mt-3 font-semibold">{error}</p>
        </div>
      </Card>
    )
  }

  if (!url) {
    return (
      <Card className="flex min-h-[32rem] items-center justify-center border-border/80 bg-panel/95 px-6 text-sm text-text-muted">
        <LoaderCircle aria-hidden="true" className="mr-2 size-5 animate-spin text-accent motion-reduce:animate-none" />
        Opening {filename}
      </Card>
    )
  }

  return (
    <div className="grid gap-3 lg:sticky lg:top-6">
      <div className="rounded-2xl border border-border/80 bg-panel-muted/35 px-4 py-3 text-sm text-text-muted">
        <p className="font-semibold text-text">PDF reference</p>
        <p className="mt-1 truncate">{filename}</p>
      </div>
      <iframe
        className="h-[72vh] min-h-[36rem] w-full rounded-2xl border border-border/80 bg-panel shadow-panel"
        src={url}
        title={`PDF preview for ${filename}`}
      />
    </div>
  )
}
