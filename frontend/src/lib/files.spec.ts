import { afterEach, describe, expect, it, vi } from 'vitest'
import { acceptsFile, bustCache, filterFiles, formatBytes, mergeFiles, triggerDownload } from './files'

function file(name: string, type = '', size = 3, lastModified = 1): File {
  return new File(['x'.repeat(size)], name, { type, lastModified })
}

describe('formatBytes', () => {
  it('escolhe a unidade e usa vírgula decimal', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1536)).toBe('1,5 KB')
    expect(formatBytes(12.3 * 1024 ** 2)).toBe('12,3 MB')
    expect(formatBytes(1.5 * 1024 ** 3)).toBe('1,5 GB')
  })
})

describe('acceptsFile', () => {
  it('sem filtro aceita tudo', () => {
    expect(acceptsFile(file('a.xyz'), '')).toBe(true)
    expect(acceptsFile(file('a.xyz'), ' , ')).toBe(true)
  })

  it('confere extensão, sem ligar para maiúsculas', () => {
    expect(acceptsFile(file('Roteiro.TXT'), '.txt,.md')).toBe(true)
    expect(acceptsFile(file('livro.docx'), '.txt,.md')).toBe(false)
  })

  it('confere família e tipo exato', () => {
    expect(acceptsFile(file('a.wav', 'audio/wav'), 'audio/*')).toBe(true)
    expect(acceptsFile(file('a.mp4', 'video/mp4'), 'audio/*,video/mp4')).toBe(true)
    expect(acceptsFile(file('a.mov', 'video/quicktime'), 'video/mp4')).toBe(false)
  })

  it('o tipo em branco de alguns navegadores passa pela extensão', () => {
    expect(acceptsFile(file('a.mkv', ''), 'video/*')).toBe(false)
    expect(acceptsFile(file('a.mkv', ''), 'video/*,.mkv')).toBe(true)
  })
})

describe('filterFiles', () => {
  it('separa o aceito, o de tipo errado e o grande demais', () => {
    const ok = file('a.txt', 'text/plain', 10)
    const wrong = file('b.pdf', 'application/pdf', 10)
    const big = file('c.txt', 'text/plain', 5000)
    const result = filterFiles([ok, wrong, big], '.txt', 1000)
    expect(result.accepted).toEqual([ok])
    expect(result.rejected).toEqual([wrong])
    expect(result.tooBig).toEqual([big])
  })

  it('sem limite de tamanho, o tamanho não pesa', () => {
    expect(filterFiles([file('a.txt', '', 5000)], '.txt').accepted).toHaveLength(1)
  })
})

describe('mergeFiles', () => {
  it('soma os novos sem repetir o mesmo arquivo', () => {
    const a = file('a.txt')
    const b = file('b.txt')
    expect(mergeFiles([a], [file('a.txt'), b])).toEqual([a, b])
  })

  it('arquivos com o mesmo nome mas conteúdo ou data diferentes são arquivos diferentes', () => {
    const merged = mergeFiles([file('a.txt', '', 3, 1)], [file('a.txt', '', 4, 1), file('a.txt', '', 3, 2)])
    expect(merged).toHaveLength(3)
  })
})

describe('bustCache', () => {
  it('acrescenta o parâmetro respeitando a query que já existe', () => {
    expect(bustCache('/api/x.wav', 7)).toBe('/api/x.wav?t=7')
    expect(bustCache('/api/voices/audio?path=a', 'abc def')).toBe('/api/voices/audio?path=a&t=abc%20def')
  })
})

describe('triggerDownload', () => {
  afterEach(() => vi.restoreAllMocks())

  it('cria um link com o nome, clica nele e o tira da página', () => {
    const clicks: Array<{ href: string; download: string }> = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push({ href: this.getAttribute('href') ?? '', download: this.download })
      expect(document.body.contains(this)).toBe(true)
    })
    triggerDownload('/api/dub/file?path=a.zip&download=true', 'trilhas.zip')
    expect(clicks).toEqual([{ href: '/api/dub/file?path=a.zip&download=true', download: 'trilhas.zip' }])
    expect(document.body.querySelector('a[download]')).toBeNull()
  })
})
