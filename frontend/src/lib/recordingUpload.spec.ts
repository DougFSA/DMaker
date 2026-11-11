import { describe, expect, it } from 'vitest'
import { ChunkUploader } from './recordingUpload'

const bytes = (size = 4) => new Uint8Array(new ArrayBuffer(size))
const noWait = { sleep: async () => undefined }

describe('o envio dos pedaços', () => {
  it('manda os pedaços em ordem e confirma cada um', async () => {
    const sent: number[] = []
    const uploader = new ChunkUploader(async (seq) => void sent.push(seq), noWait)
    for (let seq = 0; seq < 5; seq += 1) uploader.send(seq, bytes())
    await uploader.flush()
    expect(sent).toEqual([0, 1, 2, 3, 4])
    expect([...uploader.acknowledged]).toEqual([0, 1, 2, 3, 4])
    expect(uploader.pending).toBe(0)
  })

  it('uma falha de rede repete o mesmo pedaço antes dos seguintes, com espera crescente', async () => {
    const sent: number[] = []
    const waits: number[] = []
    let failures = 2
    const uploader = new ChunkUploader(
      async (seq) => {
        if (seq === 1 && failures > 0) {
          failures -= 1
          throw new Error('rede caiu')
        }
        sent.push(seq)
      },
      { baseDelayMs: 100, maxDelayMs: 1000, sleep: async (ms) => void waits.push(ms) },
    )
    for (let seq = 0; seq < 3; seq += 1) uploader.send(seq, bytes())
    await uploader.flush()
    expect(sent).toEqual([0, 1, 2])
    expect(waits).toEqual([100, 200])
  })

  it('a espera para de crescer no teto', async () => {
    const waits: number[] = []
    let failures = 6
    const uploader = new ChunkUploader(
      async () => {
        if (failures > 0) {
          failures -= 1
          throw new Error('rede caiu')
        }
      },
      { baseDelayMs: 100, maxDelayMs: 500, sleep: async (ms) => void waits.push(ms) },
    )
    uploader.send(0, bytes())
    await uploader.flush()
    expect(waits).toEqual([100, 200, 400, 500, 500, 500])
  })

  it('pedaços mandados enquanto o envio está ocupado entram na mesma fila', async () => {
    const sent: number[] = []
    let release: () => void = () => undefined
    const uploader = new ChunkUploader(async (seq) => {
      if (seq === 0) await new Promise<void>((resolve) => (release = resolve))
      sent.push(seq)
    }, noWait)
    uploader.send(0, bytes())
    uploader.send(1, bytes())
    uploader.send(2, bytes())
    expect(uploader.pending).toBe(3) // o 0 ainda em voo
    release()
    await uploader.flush()
    expect(sent).toEqual([0, 1, 2])
  })

  it('abandonar a fila para de tentar e o flush avisa', async () => {
    let calls = 0
    const uploader = new ChunkUploader(
      async () => {
        calls += 1
        throw new Error('servidor fora')
      },
      {
        sleep: async () => {
          uploader.abandon(new Error('desisti'))
        },
      },
    )
    uploader.send(0, bytes())
    await expect(uploader.flush()).rejects.toThrow('desisti')
    expect(calls).toBe(1)
    uploader.send(1, bytes()) // depois de abandonar, nada mais entra
    expect(uploader.pending).toBe(0)
  })

  it('uma recusa que repetir não conserta (4xx) para o envio e o flush rejeita com o motivo', async () => {
    let calls = 0
    const uploader = new ChunkUploader(
      async () => {
        calls += 1
        throw new Error('recusado')
      },
      { ...noWait, isFatal: (error) => error instanceof Error && error.message === 'recusado' },
    )
    uploader.send(0, bytes())
    uploader.send(1, bytes())
    await expect(uploader.flush()).rejects.toThrow('recusado')
    expect(calls).toBe(1)
    expect(uploader.pending).toBe(0)
  })
})
